#!/usr/bin/env python3
"""Unit tests for json_patch custom module."""

import json
import os
import sys
import unittest

# Add parent directory to path for importing json_patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from json_patch import JSONPatcher


class TestJSONPatcher(unittest.TestCase):
    """Test JSONPatcher operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.sample_json = json.dumps({
            "foo": {"one": 1, "two": 2},
            "bar": [1, 2, 3],
            "enabled": True
        })

    def test_add_operation(self):
        """Test adding a new field."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "add",
            "path": "/foo/three",
            "value": 3
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["foo"]["three"], 3)
        self.assertIsNone(tested)

    def test_add_to_array(self):
        """Test adding to an array."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "add",
            "path": "/bar/-",
            "value": 4
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["bar"][-1], 4)
        self.assertEqual(len(patcher.obj["bar"]), 4)

    def test_remove_operation(self):
        """Test removing a field."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "remove",
            "path": "/foo/one"
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertNotIn("one", patcher.obj["foo"])

    def test_replace_operation(self):
        """Test replacing a value."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "replace",
            "path": "/foo/one",
            "value": 99
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["foo"]["one"], 99)

    def test_test_operation_success(self):
        """Test testing a value that matches."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "test",
            "path": "/foo/one",
            "value": 1
        })
        modified, tested = patcher.patch()
        self.assertIsNone(modified)
        self.assertTrue(tested)

    def test_test_operation_failure(self):
        """Test testing a value that doesn't match."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "test",
            "path": "/foo/one",
            "value": 999
        })
        modified, tested = patcher.patch()
        self.assertIsNone(modified)
        self.assertFalse(tested)

    def test_invalid_json(self):
        """Test that invalid JSON raises an exception."""
        with self.assertRaises(Exception) as context:
            JSONPatcher("not valid json", {
                "op": "add",
                "path": "/foo",
                "value": "bar"
            })
        self.assertIn("invalid JSON", str(context.exception))

    def test_missing_op(self):
        """Test that missing 'op' raises ValueError."""
        with self.assertRaises(ValueError) as context:
            JSONPatcher(self.sample_json, {
                "path": "/foo"
            })
        self.assertIn("missing an 'op' member", str(context.exception))

    def test_invalid_operation(self):
        """Test that invalid operation raises ValueError."""
        with self.assertRaises(ValueError) as context:
            JSONPatcher(self.sample_json, {
                "op": "invalid_op",
                "path": "/foo"
            })
        self.assertIn("not a valid patch operation", str(context.exception))

    def test_missing_path(self):
        """Test that missing 'path' raises ValueError."""
        with self.assertRaises(ValueError) as context:
            JSONPatcher(self.sample_json, {
                "op": "add",
                "value": "test"
            })
        self.assertIn("missing a 'path' member", str(context.exception))

    def test_add_missing_value(self):
        """Test that 'add' without 'value' raises ValueError."""
        with self.assertRaises(ValueError) as context:
            JSONPatcher(self.sample_json, {
                "op": "add",
                "path": "/foo/new"
            })
        self.assertIn("does not have a 'value'", str(context.exception))

    def test_idempotency_add(self):
        """Test that adding an existing value is idempotent."""
        patcher = JSONPatcher(self.sample_json, {
            "op": "add",
            "path": "/foo/one",
            "value": 1
        })
        modified, tested = patcher.patch()
        # Adding existing value should not modify
        self.assertFalse(modified)

    def test_multiple_operations(self):
        """Test multiple operations in sequence."""
        patcher = JSONPatcher(self.sample_json,
            {
                "op": "add",
                "path": "/foo/three",
                "value": 3
            },
            {
                "op": "replace",
                "path": "/enabled",
                "value": False
            },
            {
                "op": "remove",
                "path": "/bar/0"
            }
        )
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["foo"]["three"], 3)
        self.assertEqual(patcher.obj["enabled"], False)
        self.assertEqual(patcher.obj["bar"], [2, 3])

    def test_nested_path(self):
        """Test operations on deeply nested paths."""
        nested_json = json.dumps({
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep"
                    }
                }
            }
        })
        patcher = JSONPatcher(nested_json, {
            "op": "replace",
            "path": "/level1/level2/level3/value",
            "value": "modified"
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["level1"]["level2"]["level3"]["value"], "modified")

    def test_empty_object(self):
        """Test operations on empty JSON object."""
        patcher = JSONPatcher("{}", {
            "op": "add",
            "path": "/new",
            "value": "value"
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj["new"], "value")

    def test_empty_array(self):
        """Test operations on empty JSON array."""
        patcher = JSONPatcher("[]", {
            "op": "add",
            "path": "/-",
            "value": "first"
        })
        modified, tested = patcher.patch()
        self.assertTrue(modified)
        self.assertEqual(patcher.obj[0], "first")


if __name__ == '__main__':
    unittest.main()
