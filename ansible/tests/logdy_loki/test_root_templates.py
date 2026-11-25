#!/usr/bin/env python3
"""Every template that uses logdy must pin the private Loki env path explicitly.

Backup/dump units are started by systemd (in several units with no `User=`,
i.e. root). Their HOME is then /root, so `~/.config/logdy/loki.env` would not
be the file Ansible renders for the deploy user and logdy would fall back to
the stale zshenv URL. Templates must export LOGDY_LOKI_ENV before the first
logdy call, pointing at the deploy user's 0600 file.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORT = 'export LOGDY_LOKI_ENV="/home/{{ create_user }}/.config/logdy/loki.env"'
CALL = re.compile(r"^\s*logdy\s+(info|warn|error|debug|trace)\b", re.MULTILINE)

# Templates that back systemd backup/dump units (root or ambiguous HOME).
ROOT_RUN = {
    "roles/restic/templates/restic_backup.sh.j2",
    "roles/restic/templates/mariadb_backup.sh.j2",
    "roles/restic/templates/binlog_ship.sh.j2",
    "roles/restic/templates/moodle_dump.sh.j2",
    "roles/restic/templates/dbops_dump.sh.j2",
    "roles/restic/templates/firefly_dump.sh.j2",
    "roles/restic/templates/db-backup-tier.sh.j2",
    "roles/ls_db_sync/templates/ls_db_sync.sh.j2",
    "roles/user/templates/backup.sh.j2",
    "roles/user/templates/restic_backup.sh.j2",
}


def logdy_templates():
    base = ROOT / "plays"
    found = {}
    for path in base.glob("roles/**/templates/*.j2"):
        text = path.read_text()
        if "logdy" in text and "source" in text:
            found[str(path.relative_to(base))] = text
    return found


class LogdyEnvForRootUnits(unittest.TestCase):
    def test_every_logdy_template_pins_the_env_path_before_first_call(self):
        templates = logdy_templates()
        self.assertGreaterEqual(len(templates), 10, "logdy template discovery broke")
        for name, text in sorted(templates.items()):
            with self.subTest(template=name):
                self.assertIn(EXPORT, text, "missing explicit LOGDY_LOKI_ENV export")
                call = CALL.search(text)
                if call:
                    self.assertLess(text.index(EXPORT), call.start(),
                                    "export must precede the first logdy call")

    def test_root_run_templates_are_all_covered(self):
        covered = set(logdy_templates())
        missing = ROOT_RUN - covered
        self.assertEqual(missing, set(), "root-run template not covered by the env fix")

    def test_no_template_relies_on_root_home(self):
        for name, text in sorted(logdy_templates().items()):
            with self.subTest(template=name):
                self.assertNotIn('LOGDY_LOKI_ENV="$HOME/', text)


if __name__ == "__main__":
    unittest.main()
