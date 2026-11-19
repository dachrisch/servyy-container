#!/usr/bin/env python3
"""Fixture for `dbops dump-due` — the "who is due?" question behind
`db-backup@<tier>` (WP-8R R8).

The whole point of R8 is that no dump TIME is written down anywhere except the
tenant row (`dump_schedule` + `dump_at`), and that "due" is a comparison between
the tenant's last scheduled instant and the mtime of its prepared set
(`<dump_dir>/current`) — never "did the timer fire". That makes three behaviours
load-bearing, and each one is asserted here against the REAL rendered script (no
mocked copy of the logic):

  * an immediate re-run is a no-op (the set is newer than the last instant),
  * a missed run is caught up (the set is older than the last instant),
  * a tenant whose dump another mechanism owns (moodle until R9, the high tier's
    physical set) is NEVER returned, and an unparseable cadence fails loudly
    instead of silently dumping nothing.

The script is rendered from roles/db_tier/templates/dbops.sh.j2 with a fixture
inventory, so a change to the template that breaks the due computation fails
here without Docker, a database, or the tenant inventory.
"""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/db_tier/templates/dbops.sh.j2"
)

# One row per behaviour under test. Fields the template needs are all present;
# `dump_dir` is rewritten to the per-test temporary directory before rendering.
TENANTS = [
    # daily, dumped today -> not due
    dict(
        tenant="daily_fresh", tier="business", engine="mariadb",
        server="db-business.mariadb", db="fresh", user="fresh",
        dump_schedule="daily 00:05", dump_at="00:05", dump_via="dbops",
        dump_dir="FIXTURE/daily_fresh", restic_repo="db-fresh",
    ),
    # daily, two days behind -> due
    dict(
        tenant="daily_stale", tier="business", engine="mariadb",
        server="db-business.mariadb", db="stale", user="stale",
        dump_schedule="daily 00:05", dump_at="00:05", dump_via="dbops",
        dump_dir="FIXTURE/daily_stale", restic_repo="db-stale",
    ),
    # daily, never dumped (no current/) -> due
    dict(
        tenant="daily_missing", tier="business", engine="mariadb",
        server="db-business.mariadb", db="missing", user="missing",
        dump_schedule="daily 00:05", dump_at="00:05", dump_via="dbops",
        dump_dir="FIXTURE/daily_missing", restic_repo="db-missing",
    ),
    # hourly, dumped within this hour -> not due
    dict(
        tenant="hourly_fresh", tier="business", engine="mongo",
        server="db-business.mongo", db="hourly_fresh", user="hourly_fresh",
        dump_schedule="hourly", dump_at="00", dump_via="dbops",
        dump_dir="FIXTURE/hourly_fresh", restic_repo="db-hourly-fresh",
    ),
    # hourly, two hours behind -> due
    dict(
        tenant="hourly_stale", tier="business", engine="mongo",
        server="db-business.mongo", db="hourly_stale", user="hourly_stale",
        dump_schedule="hourly", dump_at="00", dump_via="dbops",
        dump_dir="FIXTURE/hourly_stale", restic_repo="db-hourly-stale",
    ),
    # another mechanism entirely (moodle until R9): never due from this unit
    dict(
        tenant="legacy_owned", tier="business", engine="mariadb",
        server="db-business.mariadb", db="legacy", user="legacy",
        dump_schedule="hourly", dump_at="40", dump_via="moodle-dump",
        dump_dir="FIXTURE/legacy_owned", restic_repo="moodle-db",
    ),
    # another tier: never returned for `business`
    dict(
        tenant="private_stale", tier="private", engine="mariadb",
        server="db-private.mariadb", db="private", user="private",
        dump_schedule="daily 00:45", dump_at="00:45", dump_via="dbops",
        dump_dir="FIXTURE/private_stale", restic_repo="db-private",
    ),
    # nonprod: nothing dumps it
    dict(
        tenant="stage", tier="nonprod", engine="mariadb",
        server="db-nonprod.mariadb", db="stage", user="stage",
        dump_schedule="none", dump_at="", dump_via="none",
        dump_dir="", restic_repo="",
    ),
]

# A row the due computation cannot interpret. Kept in its own tier so it cannot
# mask the behaviour of the rows above.
BAD_TENANT = dict(
    tenant="bad_cadence", tier="weird", engine="mariadb",
    server="db-business.mariadb", db="bad", user="bad",
    dump_schedule="weekly", dump_at="00:05", dump_via="dbops",
    dump_dir="FIXTURE/bad_cadence", restic_repo="db-bad",
)


def render(tenants, fixture):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    body = TENANTS + [BAD_TENANT]
    body = [dict(t) for t in body]
    for t in body:
        t["dump_dir"] = t["dump_dir"].replace("FIXTURE", str(fixture))
    return env.get_template(TEMPLATE.name).render(
        db_tenants=body,
        db_tier_env_dir=str(fixture / "env"),
    )


class DumpDueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.script = self.root / "dbops"
        self.script.write_text(render(TENANTS, self.root))
        os.chmod(self.script, 0o755)

        # Prepared sets: mtime is the only input the due computation reads, and
        # the dump scripts set it with the atomic `mv new current`.
        self.mk("daily_fresh", age_seconds=60)
        self.mk("daily_stale", age_seconds=2 * 86400)
        # no daily_missing directory at all
        self.mk("hourly_fresh", age_seconds=60)
        self.mk("hourly_stale", age_seconds=2 * 3600)
        self.mk("legacy_owned", age_seconds=30 * 86400)
        self.mk("private_stale", age_seconds=30 * 86400)
        self.mk("bad_cadence", age_seconds=30 * 86400)

    def tearDown(self):
        self.tmp.cleanup()

    def mk(self, tenant, age_seconds):
        """Create (or refresh) <dump_dir>/current with a controlled mtime."""
        cur = self.root / tenant / "current"
        cur.mkdir(parents=True, exist_ok=True)
        stamp = time.time() - age_seconds
        os.utime(cur, (stamp, stamp))

    def run_due(self, tier, *extra):
        return subprocess.run(
            ["bash", str(self.script), "dump-due", tier, *extra],
            capture_output=True, text=True,
        )

    def test_only_due_tenants_of_that_tier_in_inventory_order(self):
        res = self.run_due("business")
        self.assertEqual(res.returncode, 0, res.stderr)
        # Inventory order, not alphabetical: daily_stale comes before the hourly
        # row it is listed above, and only rows that are actually due appear.
        self.assertEqual(
            res.stdout.split(),
            ["daily_stale", "daily_missing", "hourly_stale"],
            res.stdout,
        )
        # The moodle-owned row is 30 days stale and still NOT returned: its dump
        # belongs to another unit until R9.
        self.assertNotIn("legacy_owned", res.stdout)

    def test_immediate_rerun_is_a_noop(self):
        # Simulate the run that just happened: refresh the set to "now".
        self.mk("daily_stale", age_seconds=0)
        self.mk("hourly_stale", age_seconds=0)
        self.mk("daily_missing", age_seconds=0)
        res = self.run_due("business")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_force_returns_every_dbops_tenant_of_the_tier(self):
        # The operator override must still respect the MECHANISM boundary: it
        # never returns the moodle-owned row (its dump script is a different one)
        # and never another tier's.
        res = self.run_due("business", "--force")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.split(),
            ["daily_fresh", "daily_stale", "daily_missing", "hourly_fresh",
             "hourly_stale"],
            res.stdout,
        )
        self.assertNotIn("legacy_owned", res.stdout)
        self.assertNotIn("private_stale", res.stdout)

    def test_other_tier_is_empty_not_an_error(self):
        res = self.run_due("high")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")
        res = self.run_due("nonprod")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_uninterpretable_cadence_fails_loudly(self):
        res = self.run_due("weird")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("bad_cadence", res.stderr)
        self.assertIn("dump_schedule", res.stderr)

    def test_prerequisite_check_is_not_reachable_from_here(self):
        # `dump-due` must never dump: no docker, no credentials, nothing. If the
        # implementation ever shelled out to the engine, this fixture (which has
        # no docker binary on CI's runner path for these inputs) would fail.
        res = self.run_due("business")
        self.assertNotIn("docker", res.stderr)
        self.assertNotIn("dump failed", res.stderr)


if __name__ == "__main__":
    unittest.main()
