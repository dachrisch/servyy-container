#!/usr/bin/env python3
"""Notification-policy tests for the monitor alert-email volume fix.

The files under monitor/provisioning/alerting are the source of truth for how
often Grafana mails the admin. A regression here is silent until the inbox fills:
grouping by alertname gives one email per rule, and resolve messages double it.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ALERTING = ROOT / "monitor/provisioning/alerting"


def load(name):
    text = (ALERTING / name).read_text(encoding="utf-8")
    # contact-points.yml is a Jinja source: quote the address placeholder and
    # collapse Grafana's escaped braces the way Ansible's render does, so the
    # YAML parser sees the file Grafana actually mounts.
    text = text.replace("{{ monitor_admin_email }}", '"{{ monitor_admin_email }}"')
    text = text.replace("{{ '{{' }}", "{{")
    return yaml.safe_load(text)


class NotificationTuning(unittest.TestCase):
    def test_group_by_severity_only(self):
        """One email per severity group, not one per uniquely named rule."""
        policy = load("notification-policies.yml")
        root = policy["policies"][0]
        self.assertEqual(root["group_by"], ["severity"])
        for route in root["routes"]:
            self.assertNotIn("group_by", route)

    def test_repeat_intervals_are_relaxed(self):
        policy = load("notification-policies.yml")
        repeats = {
            route["matchers"][0].split("=", 1)[1].strip().strip('"'): route["repeat_interval"]
            for route in policy["policies"][0]["routes"]
        }
        self.assertEqual(repeats, {"critical": "1h", "high": "4h", "medium": "12h"})

    def test_resolve_messages_are_sent(self):
        """The admin wants the 'resolved' mail as well as the firing mail."""
        points = load("contact-points.yml")
        by_name = {point["name"]: point for point in points["contactPoints"]}
        self.assertEqual(set(by_name), {"email-admin", "email-critical"})
        for point in by_name.values():
            self.assertIs(point["receivers"][0]["disableResolveMessage"], False)

    def test_primary_rule_uids_are_unique(self):
        rules = load("alert-rules.yml")
        uids = [rule["uid"] for group in rules["groups"] for rule in group["rules"]]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertGreater(len(uids), 60)


if __name__ == "__main__":
    unittest.main()
