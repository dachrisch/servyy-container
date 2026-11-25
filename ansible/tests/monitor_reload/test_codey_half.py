#!/usr/bin/env python3
"""monitor_reload must restart codey's Prometheus when its config changes.

Prometheus reads its scrape config at startup only. Without a third half of this
role, editing monitor/prometheus-codey.yml would leave codey's collector running
the old config with no error — the same silent no-op this role exists to prevent.
"""

import unittest
from pathlib import Path

ROLE = Path(__file__).resolve().parents[2] / "plays/roles/monitor_reload"


class CodeyReloadHalf(unittest.TestCase):
    def test_third_task_file_fingerprints_codey_config(self):
        path = ROLE / "tasks/prometheus-codey.yml"
        self.assertTrue(path.exists(), "no prometheus-codey.yml task file")
        text = path.read_text(encoding="utf-8")
        self.assertIn("prometheus-codey.yml", text)
        self.assertIn("monitor_reload_prometheus_codey_container", text)
        self.assertIn("prometheus-codey.state", text)

    def test_main_imports_and_gates_the_new_half(self):
        text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
        self.assertIn("prometheus-codey.yml", text)
        self.assertIn("monitor_reload_prometheus_codey_enabled | bool", text)

    def test_defaults_declare_new_container_and_gate(self):
        text = (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
        self.assertIn("monitor_reload_prometheus_codey_container: monitor.prometheus-codey", text)
        self.assertIn("monitor_reload_prometheus_codey_enabled: false", text)

    def test_play_passes_the_gate(self):
        play = (Path(__file__).resolve().parents[2] / "plays/user.yml").read_text(encoding="utf-8")
        self.assertIn(
            'monitor_reload_prometheus_codey_enabled: "{{ \'ui\' in (monitor_profiles | default([])) }}"',
            play,
        )

    def test_molecule_scenario_covers_third_half(self):
        scenario = ROLE / "molecule/default"
        converge = (scenario / "converge.yml").read_text(encoding="utf-8")
        verify = (scenario / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("prometheus-codey.yml", converge)
        self.assertIn("monitor_reload_prometheus_codey_enabled: true", converge)
        self.assertIn("prometheus-codey.state", verify)


if __name__ == "__main__":
    unittest.main()
