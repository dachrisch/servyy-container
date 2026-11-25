#!/usr/bin/env python3
"""Tests for codey's local collector stack in the monitor compose project.

servyy-test runs both compose profiles, so a service added to the `ui` half must
have a container name and a host port that cannot collide with the `collect` half.
A collision there is silent on a single host but fatal on the test host.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "monitor/docker-compose.yml"
PROMETHEUS = ROOT / "monitor/prometheus-codey.yml"
DEFAULTS = ROOT / "ansible/plays/vars/default.yml"

CODEY_SERVICES = (
    "prometheus-codey",
    "node-exporter-codey",
    "cadvisor-codey",
    "pushgateway-codey",
    "pushgateway-bridge-codey",
    "promtail-codey",
)


class CodeyCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
        cls.prometheus = yaml.safe_load(PROMETHEUS.read_text(encoding="utf-8"))
        cls.defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))

    def test_codey_services_exist_in_ui_profile(self):
        for name in CODEY_SERVICES:
            with self.subTest(service=name):
                self.assertIn(name, self.compose)
                self.assertEqual(self.compose[name]["profiles"], ["ui"])

    def test_container_names_are_unique_across_profiles(self):
        names = [service["container_name"] for service in self.compose.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_codey_promtail_pushes_to_loki_route(self):
        service = self.compose["promtail-codey"]
        self.assertEqual(service["environment"], ["LOKI_PUSH_URL=${LOKI_PUSH_URL}"])
        self.assertIn("proxy", service["networks"])
        self.assertIn("./rendered/loki-password:/etc/promtail/loki-password:ro", service["volumes"])

    def test_codey_bridge_uses_port_9092(self):
        """9091 is bound by the collect bridge when both profiles run on test."""
        bridge = self.compose["pushgateway-bridge-codey"]
        self.assertEqual(bridge["ports"], ["127.0.0.1:9092:9091"])

    def test_codey_prometheus_scrapes_local_exporters(self):
        jobs = {job["job_name"] for job in self.prometheus["scrape_configs"]}
        self.assertEqual(
            jobs,
            {"prometheus-codey", "pushgateway-codey", "node-exporter-codey", "cadvisor-codey"},
        )
        by_name = {job["job_name"]: job for job in self.prometheus["scrape_configs"]}
        self.assertTrue(by_name["pushgateway-codey"]["honor_labels"])

    def test_prometheus_codey_config_is_world_readable(self):
        paths = self.defaults["world_readable_paths_by_service"]["monitor"]
        self.assertIn("prometheus-codey.yml", paths)
        self.assertIn("loki.yml", paths)  # existing collect profile must stay covered


if __name__ == "__main__":
    unittest.main()
