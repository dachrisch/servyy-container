#!/usr/bin/env python3
"""Contract for the two-server overview dashboard.

Every metric must appear once per host with an explicit datasource. A panel that
falls back to the default datasource would silently show only servy, which is
the exact blind spot this dashboard exists to close.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD = ROOT / "monitor/provisioning/dashboards/infrastructure/fleet-overview.json"
SERIES = ("prometheus", "prometheus-codey")


class FleetDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    def test_dashboard_is_named_for_both_hosts(self):
        self.assertEqual(self.doc["uid"], "fleet-overview")
        self.assertIn("servy", self.doc["title"])
        self.assertIn("codey", self.doc["title"])

    def test_panels_have_explicit_datasources(self):
        panels = [p for p in self.doc["panels"] if p["type"] != "row"]
        self.assertGreaterEqual(len(panels), 16)
        for panel in panels:
            with self.subTest(panel=panel["title"]):
                self.assertEqual(panel["datasource"]["type"], "prometheus")
                self.assertIn(panel["datasource"]["uid"], SERIES)
                self.assertTrue(panel["title"].startswith(("servy", "codey")))
                self.assertEqual(len(panel["targets"]), 1)
                self.assertEqual(panel["targets"][0]["datasource"]["uid"], panel["datasource"]["uid"])
                self.assertTrue(panel["targets"][0]["expr"])

    def test_each_metric_is_shown_for_both_hosts(self):
        panels = [p for p in self.doc["panels"] if p["type"] != "row"]
        metrics = {p["title"].split(" — ", 1)[-1] for p in panels}
        self.assertGreaterEqual(len(metrics), 8)
        for metric in metrics:
            pair = [p for p in panels if p["title"] == f"servy — {metric}"] + [
                p for p in panels if p["title"] == f"codey — {metric}"
            ]
            self.assertEqual({p["datasource"]["uid"] for p in pair}, set(SERIES), metric)

    def test_queries_do_not_hardcode_hostnames(self):
        text = DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn("lehel.xyz", text)
        self.assertNotIn("servyy-test", text)


if __name__ == "__main__":
    unittest.main()
