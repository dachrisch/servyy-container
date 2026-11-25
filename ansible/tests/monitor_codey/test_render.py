#!/usr/bin/env python3
"""The Loki push credential must be rendered on both halves of the monitor stack."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USER_PLAY = ROOT / "ansible/plays/user.yml"


class LokiPasswordRender(unittest.TestCase):
    def test_render_runs_for_ui_profile_too(self):
        text = USER_PLAY.read_text(encoding="utf-8")
        match = re.search(
            r"- name: Render the Loki basic-auth password for promtail and Prometheus.*?(?=\n    - name:)",
            text,
            re.S,
        )
        self.assertIsNotNone(match, "render task not found")
        block = match.group(0)
        self.assertIn("'collect' in (monitor_profiles", block)
        self.assertIn("'ui' in (monitor_profiles", block)
        self.assertNotIn("no_log: false", block)


if __name__ == "__main__":
    unittest.main()
