#!/usr/bin/env python3
"""Grafana provisioning tests for codey's second datasource and rule file."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DATASOURCES = ROOT / "monitor/provisioning/datasources/datasources.yml"
CODEY_RULES = ROOT / "monitor/provisioning/alerting/alert-rules-codey.yml"


class CodeyAlertRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The datasource file is a Jinja source; collapse its unquoted placeholders
        # the way Ansible does before yaml.safe_load can read it.
        text = DATASOURCES.read_text(encoding="utf-8")
        text = text.replace(
            "url: {{ monitor_prometheus_client_scheme }}://{{ monitor_prometheus_client }}",
            'url: "https://prometheus.example:443"',
        )
        text = text.replace(
            "basicAuthUser: {{ monitor_prometheus_auth_username }}",
            'basicAuthUser: "grafana"',
        )
        text = text.replace("httpHeaderValue1: {{ monitor.loki_tenant }}", 'httpHeaderValue1: "tenant"')
        cls.datasources = yaml.safe_load(text)["datasources"]
        cls.rules = yaml.safe_load(CODEY_RULES.read_text(encoding="utf-8"))

    def test_codey_datasource_points_at_local_prometheus(self):
        by_uid = {source["uid"]: source for source in self.datasources}
        self.assertEqual(set(by_uid), {"prometheus", "loki", "prometheus-codey"})
        codey = by_uid["prometheus-codey"]
        self.assertEqual(codey["url"], "http://prometheus-codey:9090")
        self.assertEqual(codey["type"], "prometheus")
        self.assertFalse(codey.get("isDefault", False))
        self.assertTrue(by_uid["prometheus"]["isDefault"])

    def test_all_codey_rules_use_the_local_datasource(self):
        rules = [rule for group in self.rules["groups"] for rule in group["rules"]]
        self.assertGreaterEqual(len(rules), 10)
        uids = [rule["uid"] for rule in rules]
        self.assertEqual(len(uids), len(set(uids)))
        for rule in rules:
            with self.subTest(rule=rule["uid"]):
                queries = [query for query in rule["data"] if query.get("refId") == "A"]
                self.assertEqual(len(queries), 1)
                self.assertEqual(queries[0]["datasourceUid"], "prometheus-codey")
                self.assertIn(rule["labels"]["severity"], {"critical", "high", "medium"})
                self.assertEqual(rule["noDataState"], "OK")
                self.assertFalse(rule["isPaused"])

    def test_codey_rules_cover_host_and_containers(self):
        uids = {rule["uid"] for group in self.rules["groups"] for rule in group["rules"]}
        self.assertIn("codey_high_memory_usage", uids)
        self.assertIn("codey_container_oom_killed", uids)
        self.assertIn("codey_container_not_running", uids)
        self.assertIn("codey_container_health_probe_stale", uids)


if __name__ == "__main__":
    unittest.main()
