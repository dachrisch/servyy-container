#!/usr/bin/env python3
"""The logdy Loki env file is rendered from the vault, never committed.

Loki moved to codey behind basic auth on 2026-11-20. The public zprezto repo
cannot hold the credential, so Ansible renders a 0600 env file that logdy
sources. These static checks pin the contract (URL, user, password, tenant,
permissions) without ever reading a real secret.
"""

import unittest
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "plays/roles/user/templates/logdy-loki.env.j2"
TASKS = ROOT / "plays/roles/user/tasks/logdy_loki.yml"
MAIN = ROOT / "plays/roles/user/tasks/main.yml"


class LogdyLokiEnv(unittest.TestCase):
    def test_template_renders_authenticated_endpoint(self):
        text = jinja2.Environment(keep_trailing_newline=True).from_string(
            TEMPLATE.read_text()
        ).render(
            monitor_loki_url="https://loki.example",
            monitor_loki_auth_username="promtail",
            monitor_remote_auth={"loki_password": "fixture-not-a-secret"},
            monitor={"loki_tenant": "tenant-x"},
        )
        self.assertIn('LOKI_URL="https://loki.example/loki/api/v1/push"', text)
        self.assertIn('LOKI_USER="promtail"', text)
        self.assertIn('LOKI_PASSWORD="fixture-not-a-secret"', text)
        self.assertIn('LOKI_TENANT_ID="tenant-x"', text)

    def test_task_writes_private_file_and_is_wired_in(self):
        tasks = TASKS.read_text()
        self.assertIn("mode: '0600'", tasks)
        self.assertIn("/home/{{ create_user }}/.config/logdy/loki.env", tasks)
        self.assertIn("logdy_loki.yml", MAIN.read_text())

    def test_no_hardcoded_host_or_credential_in_the_repo(self):
        self.assertNotIn("monitor.lehel.xyz", TEMPLATE.read_text())
        self.assertNotIn("loki_password:", TEMPLATE.read_text())


if __name__ == "__main__":
    unittest.main()
