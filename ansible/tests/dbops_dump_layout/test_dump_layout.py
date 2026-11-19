#!/usr/bin/env python3
"""Fixture for the dump-root layout rule (WP-8R follow-up, 2026-11-19).

A tenant's dump root holds exactly two things: `new/` (staging, written by the
run in progress) and `current/` (the atomic swap target — the only thing the
tenant's restic repo snapshots). A loose file in the ROOT is in no snapshot and
no probe sees it; that is how a 107 MB PhotoPrism dump sat invisible beside a
healthy `current/` for a day.

Two functions in the REAL rendered `dbops` carry that rule, and both are asserted
here without Docker:

  dump_write_dir  `dbops dump` must stage into `<dump_dir>/new`, never the root,
                  unless an operator names a directory explicitly
                  (DBOPS_DUMP_DIR / DBOPS_DUMP_DIR override).
  dump_read_dir   `dbops verify` must read the prepared set (`<dump_dir>/current`)
                  and must not fall back to a loose file in the root when that
                  exists. leaguesphere's dump_dir IS the prepared set, so the
                  `/current` suffix is only added when the directory exists.

The functions are extracted from the rendered template text, so a change that
re-introduces "dump into the root" or "read the root when current/ exists" fails
here.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/db_tier/templates/dbops.sh.j2"
)

TENANT = dict(
    tenant="fixture", tier="business", engine="mariadb",
    server="db-business.mariadb", db="fixture", user="fixture",
    dump_schedule="daily 01:05", dump_at="01:05", dump_via="dbops",
    dump_dir="FIXTURE/fixture", restic_repo="db-fixture",
)


def render(fixture):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    row = dict(TENANT)
    row["dump_dir"] = row["dump_dir"].replace("FIXTURE", str(fixture))
    return env.get_template(TEMPLATE.name).render(
        db_tenants=[row],
        db_tier_env_dir=str(fixture / "env"),
    )


def functions(script, names):
    """Return the text of the named shell functions from the rendered script."""
    out = []
    for name in names:
        match = re.search(
            r"^%s\(\) \{.*?^\}\n" % re.escape(name), script, re.S | re.M
        )
        if match is None:
            raise AssertionError("function %s not found in the rendered dbops" % name)
        out.append(match.group(0))
    # The functions read DUMP_DIR_OVERRIDE, which the script assigns once from
    # DBOPS_DUMP_DIR: take that assignment from the rendered text too, so the
    # test exercises the real env-var contract instead of a fixture reimplementation.
    assign = re.search(r"^DUMP_DIR_OVERRIDE=.*$", script, re.M)
    if assign is None:
        raise AssertionError("DUMP_DIR_OVERRIDE assignment not found in the rendered dbops")
    out.insert(0, assign.group(0))
    return "\n".join(out)


class DumpLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        script = render(self.root)
        self.body = functions(script, ("dump_write_dir", "dump_read_dir"))
        self.dump_dir = self.root / "dump"
        self.dump_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, func, **env):
        """Run one extracted function in bash with the given environment."""
        cmd = ['bash', '-c', 'set -uo pipefail\n%s\n%s' % (self.body, func)]
        base = {"PATH": os.environ["PATH"]}
        base.update(env)
        done = subprocess.run(
            cmd, env=base, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_dump_stages_into_new_never_the_root(self):
        out = self.call("dump_write_dir", T_DUMP_DIR=str(self.dump_dir))
        self.assertEqual(out, str(self.dump_dir / "new"))

    def test_dump_explicit_override_is_honoured(self):
        # The generated dump-<tenant>.sh points this at its own new/; an operator
        # may name any directory on purpose.
        out = self.call(
            "dump_write_dir",
            T_DUMP_DIR=str(self.dump_dir),
            DBOPS_DUMP_DIR="/somewhere/else",
        )
        self.assertEqual(out, "/somewhere/else")

    def test_read_prefers_current(self):
        (self.dump_dir / "current").mkdir()
        out = self.call("dump_read_dir", T_DUMP_DIR=str(self.dump_dir))
        self.assertEqual(out, str(self.dump_dir / "current"))

    def test_read_keeps_a_flat_layout_when_there_is_no_current(self):
        # leaguesphere's dump_dir IS the prepared set (mariadb-backup writes
        # there), so a missing `/current` must NOT be invented.
        out = self.call("dump_read_dir", T_DUMP_DIR=str(self.dump_dir))
        self.assertEqual(out, str(self.dump_dir))

    def test_read_override_wins(self):
        (self.dump_dir / "current").mkdir()
        out = self.call(
            "dump_read_dir",
            T_DUMP_DIR=str(self.dump_dir),
            DBOPS_DUMP_DIR="/somewhere/else",
        )
        self.assertEqual(out, "/somewhere/else")


if __name__ == "__main__":
    unittest.main()
