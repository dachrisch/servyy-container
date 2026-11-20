#!/usr/bin/env python3
"""The reaper may only judge the row that currently backs the account.

`db_user` is deterministic (`dbeaver_prod_<handle>`) and stays on dropped rows,
so `dbaccess_request` keeps one person's whole history under that single key.
On 2026-11-20 the verdict read `MIN(created_at)` over every row with that key:
a session created at 08:00Z was dropped as `past-cap` at 08:55Z - 3m50s after
the sidecar activated it - because a 13.11. row was still in the table, 166
hours old. Every later session for that person died the same way.

These tests render the REAL template (no copy of the query lives here) and pin
the two halves of the fix:

  * the cap is measured only over rows that currently back the account
    (`approved`/`active`/`revoke_requested`/`expired`), so a historical
    `dropped` row can never drive it;
  * `approved` is part of that live set - it is the window between CREATE USER
    and the row update, which the session-kill pass already spares.

The cap itself stays `${CAP_H}` from the role, never a literal.
"""

import re
import unittest
from pathlib import Path

import jinja2

ROLE = Path(__file__).resolve().parents[2] / "plays/roles/ls_dbeaver_access"
TEMPLATE = ROLE / "templates/ls-db-access-reap.sh.j2"

# One stack is enough to exercise the verdict; fields are those discover.yml
# passes. `admin_env_path` is empty for an app-owned stack (prod is one).
STACKS = [
    dict(
        db_container="leaguesphere.db",
        db_name="web35_db8",
        grant_host_pattern="172.25.%",
        ttl_cap_hours=8,
        admin_env_path="",
    )
]

LIVE_STATES = ("approved", "active", "revoke_requested", "expired")

VERDICT = re.compile(
    r"verdict=\$\(sql \"\$DB_CONTAINER\" <<SQL\n(?P<sql>.*?)\nSQL\n\)",
    re.DOTALL,
)


def render() -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)),
        undefined=jinja2.StrictUndefined,
    )
    return env.get_template(TEMPLATE.name).render(dbeaver_stacks=STACKS)


def verdict_sql() -> str:
    match = VERDICT.search(render())
    if match is None:
        raise AssertionError(
            "the verdict query is no longer a `sql \"$DB_CONTAINER\" <<SQL` "
            "heredoc - update this test together with the template"
        )
    return " ".join(match.group("sql").split())


class VerdictQueryTest(unittest.TestCase):
    def setUp(self):
        self.sql = verdict_sql()
        self.where = self.sql.split("WHERE", 1)[1] if "WHERE" in self.sql else ""

    def test_rendered_stack_carries_the_role_cap(self):
        self.assertIn("leaguesphere.db|web35_db8|172.25.%|8|", render())

    def test_verdict_keys_on_the_deterministic_account(self):
        self.assertIn("db_user='${user}'", self.where)

    def test_cap_is_measured_only_over_live_rows(self):
        # The regression: without a state predicate, MIN(created_at) reaches
        # back to the person's first-ever session and everything is past-cap.
        self.assertIn("state IN (", self.where)
        for state in LIVE_STATES:
            self.assertIn(f"'{state}'", self.where)

    def test_historical_dropped_rows_cannot_drive_the_cap(self):
        states = re.search(r"state IN \(([^)]*)\)", self.where)
        self.assertIsNotNone(states, "the verdict must filter by state")
        listed = re.findall(r"'([^']+)'", states.group(1))
        self.assertNotIn("dropped", listed)
        self.assertNotIn("failed", listed)

    def test_mint_window_is_not_reaped(self):
        # `approved` is live: the sidecar holds it between CREATE USER and the
        # UPDATE that flips the row to 'active'.
        self.assertIn("'approved'", self.where)

    def test_verdict_branches_stay_in_order(self):
        self.assertRegex(
            self.sql,
            r"WHEN COUNT\(\*\) = 0 THEN 'no-request-row' "
            r"WHEN MIN\(created_at\) < NOW\(\) - INTERVAL \$\{CAP_H\} HOUR "
            r"THEN 'past-cap' "
            r"ELSE 'ok'",
        )

    def test_cap_comes_from_the_role_not_a_literal(self):
        self.assertIn("INTERVAL ${CAP_H} HOUR", self.sql)
        self.assertNotRegex(self.sql, r"INTERVAL \d+ HOUR")


if __name__ == "__main__":
    unittest.main()
