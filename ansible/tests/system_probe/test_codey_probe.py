#!/usr/bin/env python3
"""Only the container-health probe runs on codey, against its own Pushgateway.

All other probes read servy-only state (restic repos, dump dirs, Moodle, the
storagebox mount). Enabling them on codey would page on -1 forever. The generic
no-sink cleanup must therefore keep exactly this one timer.
"""

import unittest
from pathlib import Path

ROLE = Path(__file__).resolve().parents[2] / "plays/roles/system_probe"


class CodeyContainerProbe(unittest.TestCase):
    def test_defaults_have_separate_gate_and_local_port(self):
        text = (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
        self.assertIn("system_probe_container_push_enabled:", text)
        self.assertIn("'ui' in (monitor_profiles | default([]))", text)
        self.assertIn("9092", text)

    def test_container_probe_tasks_use_the_separate_gate(self):
        text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
        self.assertIn("system_probe_container_push_enabled | default(false) | bool", text)

    def test_no_sink_cleanup_exempts_container_health(self):
        text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
        cleanup = text[text.index("Clean up all probes when Pushgateway sink is absent"):]
        self.assertIn("item == 'system-container-health'", cleanup)

    def test_molecule_no_sink_scenario_covers_ui_shape(self):
        scenario = ROLE / "molecule/no-sink"
        converge = (scenario / "converge.yml").read_text(encoding="utf-8")
        verify = (scenario / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("monitor_profiles: [ui]", converge)
        self.assertIn("system-container-health", verify)
        self.assertIn("pushed=1", verify)


if __name__ == "__main__":
    unittest.main()
