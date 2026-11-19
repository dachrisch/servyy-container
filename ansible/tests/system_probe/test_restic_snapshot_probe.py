#!/usr/bin/env python3
"""Two-group fixture for the restic snapshot-age probe.

The probe (roles/system_probe/templates/restic_snapshot_freshness.sh.j2) reports
"how old is the newest snapshot in this repo". It used to ask restic for
``snapshots --latest 1`` and read ``[0]`` of the JSON — but ``--latest 1``
returns one snapshot per **(hostname, paths) group**, so ``[0]`` is the first
group, not the newest snapshot. A single snapshot taken with a different
hostname (a branch-rendered test run, 2026-11-18) became its own group, sorted
first, and its age grew without bound: ``repo="home"`` reported 10 440 s while
the real newest snapshot was 1 612 s old — a medium alert that could never clear.

Nothing about restic is mocked away: the fixture feeds the probe the exact JSON
shape restic prints, and the fake ``restic`` honours ``--latest`` the way the
real one does, so this test fails against the old ``[0]`` code and passes only
when the probe takes the maximum over the whole repo.
"""

import datetime
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/system_probe/templates/restic_snapshot_freshness.sh.j2"
)

# The fake restic: real `snapshots --latest 1` prints the newest snapshot of
# EACH (hostname, paths) group, in group order; without --latest it prints them
# all. That difference is the entire bug, so it has to be reproduced faithfully.
FAKE_RESTIC = r'''#!/usr/bin/env python3
import json, os, sys
snaps = json.load(open(os.environ["RESTIC_FIXTURE"]))
if "--latest" in sys.argv:
    groups, newest = {}, []
    for s in snaps:
        key = (s.get("hostname"), tuple(s.get("paths") or []))
        if key not in groups:
            groups[key] = s
            newest.append(s)          # first snapshot of a group = its latest,
    print(json.dumps(newest))          # because the fixture is time-ordered
else:
    print(json.dumps(snaps))
'''

# Captures the PUT body the probe pipes into the Pushgateway.
FAKE_CURL = r'''#!/bin/sh
cat > "$CURL_CAPTURE"
'''

ENV_FILE_STUB = ""


def render(template_vars):
    text = TEMPLATE.read_text()
    return jinja2.Environment(keep_trailing_newline=True).from_string(text).render(**template_vars)


def snapshot(short_id, hostname, path, when):
    """One snapshot in restic's --json shape (times carry offsets + fractions)."""
    return {
        "short_id": short_id,
        "hostname": hostname,
        "paths": [path],
        "time": when.isoformat(timespec="microseconds"),
    }


class ProbeRun:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "bin").mkdir()
        for name, body in (("restic", FAKE_RESTIC), ("curl", FAKE_CURL)):
            path = self.root / "bin" / name
            path.write_text(body)
            path.chmod(0o755)
        self.env_file = self.root / "env.fixture"
        self.env_file.write_text(ENV_FILE_STUB)
        self.capture = self.root / "pushed.txt"

    def run(self, fixture):
        (self.root / "fixture.json").write_text(json.dumps(fixture))
        script = self.root / "system-restic-snapshots.sh"
        script.write_text(
            render(
                {
                    "system_probe_pushgateway_url": "http://pushgateway.invalid:9091",
                    "system_probe_restic_repos": [
                        {
                            "name": "fixture",
                            "env_file": str(self.env_file),
                            "threshold_seconds": 7200,
                            "severity": "medium",
                        }
                    ],
                }
            )
        )
        script.chmod(0o755)
        env = dict(os.environ)
        env.update(
            PATH=f"{self.root / 'bin'}:{env['PATH']}",
            RESTIC_FIXTURE=str(self.root / "fixture.json"),
            CURL_CAPTURE=str(self.capture),
        )
        proc = subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True, check=True
        )
        return self.capture.read_text() + proc.stdout

    def close(self):
        self.tmp.cleanup()


def metric(body, name, label):
    """The single sample value of ``name{<label>}`` in a push body."""
    values = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(name + "{") and label in line.split("}")[0]:
            values.append(float(line.split()[-1]))
    if len(values) != 1:
        raise AssertionError(f"{name}{{{label}}}: expected exactly one sample, got {values}")
    return values[0]


class NewestAcrossGroups(unittest.TestCase):
    def setUp(self):
        self.probe = ProbeRun()
        self.addCleanup(self.probe.close)

    def test_newest_overall_wins_over_the_first_group(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        stray_age, newest_age = 10_800, 2_160
        fixture = [
            # Its own group: hostname "localhost". Older, and first in the
            # `--latest 1` output — this is the one `[0]` used to pick.
            snapshot("aaaa1111", "localhost", "/home/cda", now - datetime.timedelta(seconds=stray_age)),
            # The repo's real newest snapshot, in the host's own group.
            snapshot("bbbb2222", "servy.lehel.xyz", "/home/cda", now - datetime.timedelta(seconds=newest_age)),
            snapshot("cccc3333", "servy.lehel.xyz", "/home/cda", now - datetime.timedelta(seconds=5_400)),
        ]
        body = self.probe.run(fixture)

        reported = metric(body, "restic_snapshot_age_seconds", 'repo="fixture"')
        self.assertAlmostEqual(reported, newest_age, delta=10,
                               msg="the age must be the newest snapshot, not `[0]`")
        self.assertGreater(abs(reported - stray_age), 600,
                           "the stray group's age must not be reported")

    def test_an_empty_repo_stays_unverifiable(self):
        # No snapshots at all is "unverifiable" (-1), never a crash and never a
        # silent 0: the alert rule normalises -1 into a page.
        body = self.probe.run([])
        self.assertEqual(metric(body, "restic_snapshot_age_seconds", 'repo="fixture"'), -1)

    def test_a_snapshot_at_or_after_the_sample_is_clamped_to_zero(self):
        # A snapshot stamped AFTER the probe sampled `now` yields a negative age,
        # and the alert rules treat ANY negative age as "unverifiable" and page.
        # The window is small, but the 5-minute binlog repo hits it 12x more often
        # than an hourly one — measured 2026-11-19: repo="ls-binlog" reported -2
        # on a probe run that raced the :03 snapshot. It must report 0 (the repo
        # WAS read, the newest snapshot is simply now-or-later), while -1 stays
        # reserved for "could not read the repo".
        now = datetime.datetime.now(datetime.timezone.utc)
        fixture = [
            snapshot("dddd4444", "servy.lehel.xyz", "/home/cda",
                     now + datetime.timedelta(seconds=60)),
        ]
        body = self.probe.run(fixture)
        self.assertEqual(metric(body, "restic_snapshot_age_seconds", 'repo="fixture"'), 0)


if __name__ == "__main__":
    unittest.main()
