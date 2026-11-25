#!/usr/bin/env python3
"""Static checks for the restic maintenance failure/staleness rules.

The old `Stale Maintenance/Backup Log` rule only checked file freshness;
`forget.log` and `check.log` are written even when restic fails, so a dead
maintenance run was invisible for weeks. These rules read the per-repo outcome
gauge pushed by the forget/check scripts plus Pushgateway's `push_time_seconds`.

The PromQL itself is also evaluated read-only against the live Grafana with
`POST /api/v1/eval` (failing / fresh / absent cases) before the rules ship.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "monitor/provisioning/alerting/alert-rules.yml"


class ResticMaintenanceRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(RULES.read_text())
        cls.groups = {g["name"]: g for g in cls.doc["groups"]}

    def all_rules(self):
        return [rule for group in self.doc["groups"] for rule in group["rules"]]

    def test_group_and_rule_uids(self):
        self.assertIn("restic-maintenance-alerts", self.groups)
        uids = {rule["uid"] for rule in self.groups["restic-maintenance-alerts"]["rules"]}
        self.assertEqual(uids, {"restic_maintenance_failure", "restic_maintenance_stale"})

    def test_failure_rule_pages_any_zero_repo(self):
        rule = next(
            r for r in self.groups["restic-maintenance-alerts"]["rules"]
            if r["uid"] == "restic_maintenance_failure"
        )
        expr = rule["data"][0]["model"]["expr"]
        self.assertIn("restic_maintenance_success", expr)
        # Prometheus `== 0` filters but returns the LEFT value (0), which the
        # rule's `> 0.5` threshold can never pass. `bool` converts to 0/1.
        self.assertIn("== bool 0", expr)
        self.assertEqual(rule["noDataState"], "OK")  # absence is the stale rule's job
        self.assertEqual(rule["labels"]["severity"], "medium")

    def test_stale_rule_covers_both_ops_with_absent_and_no_data_alerting(self):
        rule = next(
            r for r in self.groups["restic-maintenance-alerts"]["rules"]
            if r["uid"] == "restic_maintenance_stale"
        )
        expr = rule["data"][0]["model"]["expr"]
        self.assertIn('job="restic_maintenance_forget"', expr)
        self.assertIn('job="restic_maintenance_check"', expr)
        self.assertIn("129600", expr)  # > 36 h for a daily forget
        self.assertIn("691200", expr)  # > 8 d for a weekly check
        self.assertEqual(expr.count("absent("), 2)
        # Rejected pushes create push_time_seconds 0; every use must filter it.
        import re
        self.assertEqual(len(re.findall(r'push_time_seconds\{job="[^"]+"\} > 0', expr)), 4)
        self.assertEqual(rule["noDataState"], "Alerting")

    def test_rule_uids_are_unique_and_use_the_servy_datasource(self):
        uids = [rule["uid"] for rule in self.all_rules()]
        self.assertEqual(len(uids), len(set(uids)))
        for rule in self.groups["restic-maintenance-alerts"]["rules"]:
            with self.subTest(rule=rule["uid"]):
                self.assertEqual(rule["data"][0]["datasourceUid"], "prometheus")
                self.assertEqual(rule["data"][0]["model"]["refId"], "A")


if __name__ == "__main__":
    unittest.main()
