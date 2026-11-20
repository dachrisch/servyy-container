#!/usr/bin/env python3
"""The molecule matrix must shrink with the PR without shrinking the guarantee.

Path gating trades CI minutes for the risk that a change runs nothing. These
tests pin the three behaviours that make that trade safe:

  * the eight scenarios the ruleset used to require by name are `baseline` and
    run on every ansible change, whichever role changed;
  * anything that cannot be attributed to one role (shared playbooks, vars,
    `library/`, `ansible/tests/`, an unknown role, `.github/**`) widens to the
    whole matrix rather than guessing narrow;
  * the manifest and `ansible/plays/roles/*/molecule/*/` agree in both
    directions, so a scenario can never again exist without running (the state
    `portainer_rbac/default` was in) or be listed without existing.

They also pin that a selection is never empty: `fromJSON('[]')` is a fatal
expression error in GitHub Actions, not a skip.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / ".github/scripts/molecule_matrix.py"
MANIFEST = REPO / ".github/molecule-matrix.yml"

_spec = importlib.util.spec_from_file_location("molecule_matrix", SCRIPT)
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)

# The contexts the master ruleset required by name before path gating. They stay
# unconditional: losing coverage for these is the expensive failure mode
# (boot, ssh, docker, service rendering), and their check-run names are
# unchanged, so the old ruleset kept passing while the new ci.yml landed.
REQUIRED_BEFORE_GATING = {
    ("system", "minimal"),
    ("system", "core"),
    ("system", "with-docker"),
    ("system", "default"),
    ("testing", "default"),
    ("user", "default"),
    ("user", "docker-only"),
    ("docker_service", "default"),
}


def entry(role, scenario, baseline=False, **kw):
    return {"role": role, "scenario": scenario, "baseline": baseline, **kw}


def build_root(tmp, scenarios):
    """A throwaway repo with exactly these molecule directories."""
    for role, scenario in scenarios:
        (Path(tmp) / "ansible/plays/roles" / role / "molecule" / scenario).mkdir(
            parents=True, exist_ok=True
        )
    return Path(tmp)


def names(matrix):
    return [(e["role"], e["scenario"]) for e in matrix["include"]]


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build_root(
            self._tmp.name,
            [
                ("system", "default"),
                ("system", "core"),
                ("user", "default"),
                ("restic", "default"),
                ("restic", "no-leaguesphere"),
                ("db_tier", "default"),
            ],
        )
        self.entries = [
            entry("system", "default", baseline=True),
            entry("system", "core", baseline=True),
            entry("user", "default", baseline=True),
            entry("restic", "default"),
            entry("restic", "no-leaguesphere"),
            entry("db_tier", "default"),
        ]

    def plan(self, changes, ci=False):
        return mm.plan(self.entries, self.root, changes, ci)

    def test_role_change_keeps_baseline_and_adds_that_role(self):
        matrix = self.plan(["ansible/plays/roles/restic/tasks/main.yml"])
        self.assertEqual(
            names(matrix),
            [
                ("system", "default"),
                ("system", "core"),
                ("user", "default"),
                ("restic", "default"),
                ("restic", "no-leaguesphere"),
            ],
        )

    def test_sibling_scenario_joins_when_its_role_changes(self):
        matrix = self.plan(["ansible/plays/roles/restic/templates/backup.sh.j2"])
        self.assertIn(("restic", "no-leaguesphere"), names(matrix))

    def test_markdown_inside_a_role_only_runs_that_role(self):
        matrix = self.plan(["ansible/plays/roles/db_tier/README.md"])
        self.assertIn(("db_tier", "default"), names(matrix))
        self.assertNotIn(("restic", "default"), names(matrix))

    def test_shared_playbook_runs_everything(self):
        self.assertEqual(len(names(self.plan(["ansible/plays/servyy.yml"]))), len(self.entries))

    def test_shared_vars_run_everything(self):
        self.assertEqual(len(names(self.plan(["ansible/plays/vars/secrets.yml"]))), len(self.entries))

    def test_custom_module_runs_everything(self):
        self.assertEqual(len(names(self.plan(["ansible/library/json_patch.py"]))), len(self.entries))

    def test_yamllint_config_runs_everything(self):
        self.assertEqual(len(names(self.plan([".yamllint.yml"]))), len(self.entries))

    def test_ci_change_runs_everything(self):
        self.assertEqual(len(names(self.plan([], ci=True))), len(self.entries))

    def test_unknown_role_widens_to_all(self):
        # a brand-new role directory has no molecule scenario yet, so the path
        # cannot be attributed - guess wide, never narrow
        matrix = self.plan(["ansible/plays/roles/not_in_manifest/tasks/main.yml"])
        self.assertEqual(len(names(matrix)), len(self.entries))

    def test_no_attributable_change_still_emits_baseline(self):
        # never an empty matrix: fromJSON('[]') is a fatal workflow error
        matrix = self.plan([])
        self.assertEqual(
            names(matrix),
            [("system", "default"), ("system", "core"), ("user", "default")],
        )

    def test_disabled_entry_is_never_selected(self):
        entries = self.entries + [
            entry("portainer_rbac", "default", enabled=False, reason="manual on servyy-test"),
        ]
        self.root = build_root(
            self._tmp.name,
            [
                ("system", "default"),
                ("system", "core"),
                ("user", "default"),
                ("restic", "default"),
                ("restic", "no-leaguesphere"),
                ("db_tier", "default"),
                ("portainer_rbac", "default"),
            ],
        )
        self.assertNotIn(("portainer_rbac", "default"), names(mm.plan(entries, self.root, [], True)))

    def test_matrix_follows_manifest_order(self):
        # stable order across runs keeps matrix logs and comparisons readable
        manifest_order = [(e["role"], e["scenario"]) for e in self.entries]
        matrix = self.plan(["ansible/plays/roles/restic/tasks/main.yml"])
        selected = set(names(matrix))
        self.assertEqual(names(matrix), [n for n in manifest_order if n in selected])


class ConsistencyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_scenario_without_manifest_entry_fails(self):
        root = build_root(self._tmp.name, [("system", "default"), ("newrole", "default")])
        with self.assertRaises(SystemExit) as ctx:
            mm.plan([entry("system", "default", baseline=True)], root, [], False)
        self.assertIn("newrole/default", str(ctx.exception))

    def test_stale_manifest_entry_fails(self):
        root = build_root(self._tmp.name, [("system", "default")])
        entries = [entry("system", "default", baseline=True), entry("gone", "default")]
        with self.assertRaises(SystemExit) as ctx:
            mm.plan(entries, root, [], False)
        self.assertIn("gone/default", str(ctx.exception))

    def test_misspelled_flag_fails_instead_of_demoting(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write("scenarios:\n  - {role: system, scenario: default, baselin: true}\n")
            path = Path(fh.name)
        self.addCleanup(path.unlink)
        with self.assertRaises(SystemExit) as ctx:
            mm.load_manifest(path)
        self.assertIn("baselin", str(ctx.exception))

    def test_disabled_without_reason_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write("scenarios:\n  - {role: system, scenario: default, enabled: false}\n")
            path = Path(fh.name)
        self.addCleanup(path.unlink)
        with self.assertRaises(SystemExit) as ctx:
            mm.load_manifest(path)
        self.assertIn("reason", str(ctx.exception))

    def test_duplicate_entry_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write(
                "scenarios:\n"
                "  - {role: system, scenario: default}\n"
                "  - {role: system, scenario: default}\n"
            )
            path = Path(fh.name)
        self.addCleanup(path.unlink)
        with self.assertRaises(SystemExit) as ctx:
            mm.load_manifest(path)
        self.assertIn("duplicate", str(ctx.exception))


class RepositoryManifestTest(unittest.TestCase):
    """The committed manifest must describe the committed roles."""

    def setUp(self):
        self.entries = mm.load_manifest(MANIFEST)

    def test_manifest_and_disk_agree(self):
        self.assertEqual(mm.check_consistency(self.entries, REPO), [])

    def test_baseline_is_exactly_the_formerly_required_set(self):
        baseline = {(e["role"], e["scenario"]) for e in self.entries if e.get("baseline")}
        self.assertEqual(baseline, REQUIRED_BEFORE_GATING)

    def test_every_enabled_entry_is_selected_by_a_full_run(self):
        matrix = mm.plan(self.entries, REPO, [], True)
        enabled = {(e["role"], e["scenario"]) for e in self.entries if e.get("enabled", True)}
        self.assertEqual(set(names(matrix)), enabled)

    def test_docs_only_change_waits_for_the_job_condition(self):
        # no ansible path: the plan job is skipped upstream of this script, so
        # what matters here is that the script never invents work for it
        matrix = mm.plan(self.entries, REPO, ["docs/foo.md", "README.md"], False)
        self.assertEqual(set(names(matrix)), REQUIRED_BEFORE_GATING)


if __name__ == "__main__":
    unittest.main()
