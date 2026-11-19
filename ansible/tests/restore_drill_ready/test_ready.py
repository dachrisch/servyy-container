#!/usr/bin/env python3
"""Fixture for the MariaDB scratch readiness race (WP-8R follow-up, 2026-11-19).

The firefly drill failed once with

    ERROR 2002 (HY000): Can't connect to local server through socket
    '/run/mysqld/mysqld.sock' (2)

immediately after the readiness check had returned success, and `has_tables`
(fail-safe) then read the empty answer as "already has tables", so the restore
was refused. Measured on mariadb:13.0 from container start:

    +1.0 s   socket does not exist            -> 2002
    +10.1 s  TEMP init server on that socket  -> answers, @@port = 0
    +12.3 s  temp server stopped              -> 2002
    +15.0 s  final server                     -> answers, @@port = 3306

An "authenticate and return" readiness check can therefore report ready for a
server that is killed milliseconds later. The guard is `@@port`: the temp server
runs with skip-networking and reports 0; only the real server listens.

This test renders the REAL drill script, extracts `wait_mariadb_auth`, and drives
it with a fake `docker` that replays exactly that timeline. It asserts:

  * readiness does NOT return while only the temp server answers (port 0);
  * readiness returns on the final server;
  * an authenticate-only predicate (the old check) WOULD return at the temp
    server — which is the defect being fixed, pinned so it cannot come back.
"""

import os
import shlex
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/restore_drill/templates/restore_drill.sh.j2"
)

TENANTS = [dict(
    tenant="firefly", tier="private", engine="mariadb",
    server="db-private.mariadb", db="firefly", user="firefly",
    restic_repo="db-private-firefly", dump_dir="/home/cda/db-dumps/firefly",
    drill="monthly", drill_format="logical",
)]

# What the fake server answers, attempt by attempt: 2002 (no socket), the TEMP
# init server (authenticates, port 0), the shutdown gap, then the real server.
TIMELINE = [
    ("2002", 1),
    ("2002", 1),
    ("0", 0),          # temp server: this is the trap
    ("2002", 1),
    ("2002", 1),
    ("3306", 0),
    ("3306", 0),
]

FAKE_DOCKER = textwrap.dedent("""\
    #!/usr/bin/env bash
    # Fake `docker` for the readiness fixture: replays TIMELINE by attempt count.
    state="${FAKE_DOCKER_STATE:?}"
    if [ "$1" = "inspect" ]; then echo true; exit 0; fi
    if [ "$1" != "exec" ]; then echo "unsupported fake docker call: $*" >&2; exit 1; fi
    cat >/dev/null                       # drain the password on stdin
    n=$(cat "$state" 2>/dev/null || echo 0)
    n=$((n + 1)); echo "$n" > "$state"
    line=$(sed -n "${n}p" "${FAKE_DOCKER_TIMELINE:?}")
    [ -n "$line" ] || line="3306 0"
    out="${line%% *}"; rc="${line##* }"
    {
      if [ "$out" = "2002" ]; then
        echo "ERROR 2002 (HY000): Can't connect to local server through socket '/run/mysqld/mysqld.sock' (2)" >&2
      else
        echo "$out"
      fi
    }
    exit "$rc"
""")


def render(fixture):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    # `quote` is an Ansible filter (shell quoting), not a jinja2 builtin.
    env.filters["quote"] = shlex.quote
    env.filters["bool"] = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
    return env.get_template(TEMPLATE.name).render(
        restore_drill_base_dir=str(fixture / "base"),
        restore_drill_state_dir=str(fixture / "base/state"),
        restore_drill_evidence_dir=str(fixture / "base/evidence"),
        restore_drill_log_dir=str(fixture / "base/logs"),
        restore_drill_scratch_dir=str(fixture / "scratch"),
        restore_drill_dbops_path=str(fixture / "dbops"),
        restore_drill_dbops_env_dir=str(fixture / "env"),
        restore_drill_probe_script=str(fixture / "probe"),
        restore_drill_keep_failed_scratch=False,
        restore_drill_tenants=TENANTS,
    )


class ReadinessRaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        script = render(self.root)
        match = re.search(
            r"^wait_mariadb_auth\(\) \{.*?^\}\n", script, re.S | re.M
        )
        self.assertIsNotNone(match, "wait_mariadb_auth not found in the rendered drill")
        self.body = match.group(0)

        bindir = self.root / "bin"
        bindir.mkdir()
        docker = bindir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.env = dict(os.environ)
        self.env["PATH"] = str(bindir) + ":" + self.env["PATH"]
        self.env["FAKE_DOCKER_STATE"] = str(self.root / "state")
        timeline = self.root / "timeline"
        timeline.write_text("\n".join("%s %s" % (o, r) for o, r in TIMELINE) + "\n")
        self.env["FAKE_DOCKER_TIMELINE"] = str(timeline)

    def tearDown(self):
        self.tmp.cleanup()

    def run_body(self, body):
        return subprocess.run(
            ["bash", "-c", "set -uo pipefail\n%s\n" % body],
            env=self.env, capture_output=True, text=True, timeout=60,
        )

    def test_readiness_waits_for_the_final_server(self):
        done = self.run_body(
            self.body + '\nwait_mariadb_auth drill-root root secret\n'
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        # It must have walked past the temp-server attempt (3) and only accepted
        # the real server (6): accepting attempt 3 is the measured failure.
        attempts = int((self.root / "state").read_text().strip())
        self.assertEqual(attempts, 6)

    def test_authenticate_only_would_have_returned_on_the_temp_server(self):
        # The OLD predicate, verbatim in shape: does the credential work?
        old = textwrap.dedent("""\
            old_ready() {
              local i
              for i in $(seq 1 180); do
                if printf '%s\\n' "$3" \\
                   | docker exec -i "$1" sh -c 'read -r P; exec mariadb --skip-ssl -u"$1" -p"$P" -e "select 1"' drill "$2" >/dev/null 2>&1; then
                  return 0
                fi
                docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true || return 1
                sleep 1
              done
              return 1
            }
            """)
        done = self.run_body(old + '\nold_ready drill-root root secret\n')
        self.assertEqual(done.returncode, 0, done.stderr)
        # It returned on attempt 3 — the TEMP server, @@port 0. The next query
        # then hits the shutdown gap (attempt 4), which is the 2002 in the log.
        self.assertEqual(int((self.root / "state").read_text().strip()), 3)
        after = self.run_body('docker exec -i drill-root sh -c true\n')
        self.assertNotEqual(after.returncode, 0)
        self.assertIn("2002", after.stderr)


if __name__ == "__main__":
    unittest.main()
