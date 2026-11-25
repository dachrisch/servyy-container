#!/usr/bin/env python3
"""Behavioural tests for the restic forget/check maintenance scripts.

The 2026-11-19 outage: a dead process left a stale exclusive lock on
``restic-home``; hourly backups kept saving (non-exclusive), but the daily
``forget`` and weekly ``check`` could not run. Nothing alerted because both log
files are written even on failure. The fix must self-heal *stale* locks before
each maintenance op (never ``--remove-all`` — an active backup must keep its
lock) and publish a per-repo outcome + a run timestamp to the Pushgateway.

Nothing about restic is mocked away at the script level: the rendered scripts
run under zsh against fake ``restic``/``curl`` executables and a fake logdy
function, so the assertions exercise the real control flow and the real
Pushgateway payload.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "plays/roles/system"
FORGET = SYSTEM / "templates/restic_forget.sh.j2"
CHECK = SYSTEM / "templates/restic_check.sh.j2"
BACKUP = ROOT / "plays/roles/restic/templates/restic_backup.sh.j2"

FAKE_RESTIC = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
with open(os.environ["RESTIC_CALL_LOG"], "a") as log:
    log.write(os.environ.get("RESTIC_REPOSITORY", "?") + "|" + " ".join(args) + "\n")
op = args[0] if args else ""
repo = os.environ.get("RESTIC_REPOSITORY", "")
if op in ("forget", "check") and os.environ.get("FAIL_REPO", "") in repo:
    print("simulated " + op + " failure", file=sys.stderr)
    sys.exit(1)
if op == "unlock":
    print("successfully removed 2 stale locks")
'''

FAKE_CURL = r'''#!/bin/sh
printf '%s' "$*" > "$CURL_ARGS_CAPTURE"
cat > "$CURL_CAPTURE"
'''

FAKE_LOGDY = "logdy() { printf 'LOGDY %s\\n' \"$*\" >> \"$LOGDY_CAPTURE\"; }\n"


def render(template, overrides=None):
    context = {
        "create_user": "testuser",
        "restic": {
            "logs": {"forget": "/tmp/restic-forget-fixture.log", "check": "/tmp/restic-check-fixture.log"}
        },
        "restic_targets_enabled": [
            {"name": "home", "retention": "host_hourly"},
            {"name": "db", "retention": "db_hourly"},
        ],
        "retention_profiles": {
            "host_hourly": {"last": 24, "hourly": 48},
            "db_hourly": {"last": 48, "daily": 30},
        },
        "restic_env_dir": "/tmp/restic-env-fixture",
        "restic_maintenance_pushgateway_url": "http://pushgateway.invalid:9091",
        "restic_maintenance_forget_job": "restic_maintenance_forget",
        "restic_maintenance_check_job": "restic_maintenance_check",
    }
    context.update(overrides or {})
    return jinja2.Environment(keep_trailing_newline=True).from_string(template.read_text()).render(**context)


class MaintenanceRun:
    def __init__(self, template):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "bin").mkdir()
        (self.root / "env").mkdir()
        (self.root / "home/.zprezto/custom/functions").mkdir(parents=True)
        for name, body in (("restic", FAKE_RESTIC), ("curl", FAKE_CURL)):
            path = self.root / "bin" / name
            path.write_text(body)
            path.chmod(0o755)
        (self.root / "home/.zprezto/custom/functions/logdy").write_text(FAKE_LOGDY)
        for repo in ("home", "db"):
            (self.root / "env" / f"env.{repo}").write_text(
                f'export RESTIC_REPOSITORY="/fake/{repo}"\n'
            )
        self.calls = self.root / "calls.txt"
        self.pushed = self.root / "pushed.txt"
        self.push_args = self.root / "push-args.txt"
        self.logdy = self.root / "logdy.txt"
        self.log = self.root / "maintenance.log"
        overrides = {
            "restic": {
                "logs": {"forget": str(self.log), "check": str(self.log)}
            },
            "restic_env_dir": str(self.root / "env"),
        }
        script = self.root / "maintenance.sh"
        script.write_text(render(template, overrides))
        script.chmod(0o755)
        self.script = script

    def run(self, fail_repo=""):
        env = dict(os.environ)
        env.update(
            HOME=str(self.root / "home"),
            PATH=f"{self.root / 'bin'}:{env['PATH']}",
            RESTIC_CALL_LOG=str(self.calls),
            CURL_CAPTURE=str(self.pushed),
            CURL_ARGS_CAPTURE=str(self.push_args),
            LOGDY_CAPTURE=str(self.logdy),
            FAIL_REPO=fail_repo,
        )
        proc = subprocess.run(
            ["zsh", str(self.script)], env=env, capture_output=True, text=True, timeout=30
        )
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        pushed = self.pushed.read_text() if self.pushed.exists() else ""
        return proc, calls, pushed

    def close(self):
        self.tmp.cleanup()


def call_index(calls, predicate):
    matches = [i for i, line in enumerate(calls) if predicate(line)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one call, got {matches}: {calls}")
    return matches[0]


class ForgetMaintenance(unittest.TestCase):
    def setUp(self):
        self.runner = MaintenanceRun(FORGET)
        self.addCleanup(self.runner.close)

    def test_unlock_runs_once_per_repo_before_forget_and_never_removes_all(self):
        _, calls, _ = self.runner.run()
        self.assertEqual(len([c for c in calls if "|unlock" in c]), 2, calls)
        for repo in ("home", "db"):
            unlock = call_index(calls, lambda line, r=repo: line.startswith(f"/fake/{r}|unlock"))
            forget = call_index(calls, lambda line, r=repo: line.startswith(f"/fake/{r}|forget "))
            self.assertLess(unlock, forget, f"unlock must precede forget for {repo}: {calls}")
        self.assertFalse(any("--remove-all" in c for c in calls), calls)

    def test_per_repo_success_is_pushed_even_when_one_repo_fails(self):
        proc, _, pushed = self.runner.run(fail_repo="db")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('restic_maintenance_success{op="forget",repo="home"} 1', pushed)
        self.assertIn('restic_maintenance_success{op="forget",repo="db"} 0', pushed)
        self.assertIn("# TYPE restic_maintenance_success gauge", pushed)
        self.assertIn("/metrics/job/restic_maintenance_forget", self.runner.push_args.read_text())

    def test_unlock_output_is_logged(self):
        _, _, _ = self.runner.run()
        self.assertIn("removed 2 stale locks", self.runner.log.read_text())
        self.assertIn("Stale lock check complete", self.runner.logdy.read_text())


class CheckMaintenance(unittest.TestCase):
    def setUp(self):
        self.runner = MaintenanceRun(CHECK)
        self.addCleanup(self.runner.close)

    def test_unlock_runs_before_check_and_no_remove_all(self):
        _, calls, _ = self.runner.run()
        self.assertEqual(len([c for c in calls if "|unlock" in c]), 2, calls)
        for repo in ("home", "db"):
            unlock = call_index(calls, lambda line, r=repo: line.startswith(f"/fake/{r}|unlock"))
            check = call_index(calls, lambda line, r=repo: line.startswith(f"/fake/{r}|check "))
            self.assertLess(unlock, check, f"unlock must precede check for {repo}: {calls}")
        self.assertFalse(any("--remove-all" in c for c in calls), calls)

    def test_per_repo_check_success_is_pushed(self):
        proc, _, pushed = self.runner.run(fail_repo="home")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('restic_maintenance_success{op="check",repo="home"} 0', pushed)
        self.assertIn('restic_maintenance_success{op="check",repo="db"} 1', pushed)
        self.assertIn("/metrics/job/restic_maintenance_check", self.runner.push_args.read_text())


class HourlyBackupUntouched(unittest.TestCase):
    def test_hourly_backup_does_not_unlock(self):
        self.assertNotIn("unlock", BACKUP.read_text())


if __name__ == "__main__":
    unittest.main()
