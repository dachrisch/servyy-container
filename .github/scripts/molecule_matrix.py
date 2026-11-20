#!/usr/bin/env python3
"""Choose the molecule matrix for this PR from the paths it changed.

Before path gating, every PR paid for all sixteen scenarios whether it touched
a role or a README. The matrix is now computed per PR, but the *guarantee* must
not shrink with it: the eight scenarios the ruleset used to require by name are
marked `baseline: true` in `.github/molecule-matrix.yml` and run on every
ansible change, whatever happened to change. Everything else joins only when its
own role directory was touched.

Widening beats guessing. Any of these run the whole matrix:

  * a shared ansible path (`plays/*.yml`, `plays/vars/**`, `library/**`,
    `ansible/tests/**`, `ansible/requirements*.yml`) - the changed role cannot
    be attributed from the path;
  * `.github/**` (the pipeline itself changed);
  * a role directory the manifest has never heard of.

The manifest and the disk are cross-checked on every run, so a new
`molecule/<scenario>/` without an entry - or an entry without a directory -
fails here instead of silently never running.

Usage:
  python3 .github/scripts/molecule_matrix.py \\
      --changed-files-json "$ANSIBLE_FILES" --ci-changed "$CI_CHANGED" \\
      --github-output "$GITHUB_OUTPUT"

  python3 .github/scripts/molecule_matrix.py --all      # local: every entry
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

MANIFEST = Path(".github/molecule-matrix.yml")
DIAGNOSTIC = "add the entry to .github/molecule-matrix.yml"


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Return the scenario entries, validated.

    Validation is strict on purpose: a typo in `baseline` (say `baselin: true`)
    would silently demote a guaranteed scenario to path-scoped, which is exactly
    the class of quiet coverage loss this file exists to prevent.
    """
    if not path.is_file():
        raise SystemExit(f"molecule plan: manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("scenarios")
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"molecule plan: {path} has no `scenarios` list")

    seen: set[tuple[str, str]] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise SystemExit(f"molecule plan: {path}: entry is not a mapping: {raw!r}")
        for key in ("role", "scenario"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise SystemExit(f"molecule plan: {path}: entry needs a `{key}`: {raw!r}")
        unknown = set(raw) - {"role", "scenario", "baseline", "enabled", "reason"}
        if unknown:
            raise SystemExit(
                f"molecule plan: {path}: {raw['role']}/{raw['scenario']} has unknown keys "
                f"{sorted(unknown)} (a misspelled `baseline` would silently un-guarantee it)"
            )
        for key in ("baseline", "enabled"):
            if key in raw and not isinstance(raw[key], bool):
                raise SystemExit(f"molecule plan: {path}: `{key}` must be true/false: {raw!r}")
        if raw.get("enabled") is False and not str(raw.get("reason", "")).strip():
            raise SystemExit(
                f"molecule plan: {path}: {raw['role']}/{raw['scenario']} is disabled "
                "without a `reason`"
            )
        key = (raw["role"], raw["scenario"])
        if key in seen:
            raise SystemExit(f"molecule plan: {path}: duplicate entry {key[0]}/{key[1]}")
        seen.add(key)
    return entries


def discovered(root: Path) -> set[tuple[str, str]]:
    """Every `<role>/molecule/<scenario>/` directory actually present."""
    roles_dir = root / "ansible" / "plays" / "roles"
    found: set[tuple[str, str]] = set()
    if not roles_dir.is_dir():
        return found
    for role_dir in sorted(roles_dir.iterdir()):
        molecule_dir = role_dir / "molecule"
        if not molecule_dir.is_dir():
            continue
        for scenario_dir in sorted(molecule_dir.iterdir()):
            if scenario_dir.is_dir():
                found.add((role_dir.name, scenario_dir.name))
    return found


def check_consistency(entries: list[dict[str, Any]], root: Path) -> list[str]:
    """Manifest and disk must agree in both directions."""
    declared = {(e["role"], e["scenario"]) for e in entries}
    found = discovered(root)
    problems: list[str] = []
    if found - declared:
        names = ", ".join(f"{r}/{s}" for r, s in sorted(found - declared))
        problems.append(f"molecule scenarios on disk with no manifest entry ({DIAGNOSTIC}): {names}")
    if declared - found:
        names = ", ".join(f"{r}/{s}" for r, s in sorted(declared - found))
        problems.append(f"manifest entries with no molecule directory on disk (remove them): {names}")
    return problems


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def roles_on_disk(root: Path) -> set[str]:
    return {role for role, _ in discovered(root)}


def classify(changes: list[str], roles: set[str]) -> tuple[str, set[str]]:
    """Map the changed paths to ("all", set()) or ("scoped", affected roles).

    `roles` is every role that has molecule scenarios, so a path pointing at a
    role the manifest does not know cannot be mistaken for a shared path.
    """
    affected: set[str] = set()
    for raw in changes:
        path = raw.strip()
        # only a leading "./" - lstrip("./") would eat the dot of ".yamllint.yml"
        while path.startswith("./"):
            path = path[2:]
        if not path:
            continue
        if path in (".yamllint.yml", "ansible/requirements.yml", "ansible/requirements.txt"):
            return "all", set()
        if not path.startswith("ansible/"):
            continue
        parts = path.split("/")
        # ansible/plays/roles/<role>/... - attributable to exactly one role
        if len(parts) >= 4 and parts[1] == "plays" and parts[2] == "roles":
            role = parts[3]
            if role not in roles:
                return "all", set()
            affected.add(role)
            continue
        # anything else under ansible/ is shared input (playbooks, vars, library,
        # ansible/tests, requirements) - it can affect any role, so run them all
        return "all", set()
    return "scoped", affected


def select(entries: list[dict[str, Any]], mode: str, affected: set[str]) -> list[dict[str, str]]:
    """The matrix `include` list, in manifest order (stable across runs)."""
    enabled = [e for e in entries if e.get("enabled", True)]
    if mode == "all":
        chosen = enabled
    else:
        chosen = [e for e in enabled if e.get("baseline", False) or e["role"] in affected]
    if not chosen:
        # An empty matrix is a fatal expression error in GitHub Actions
        # (`fromJSON('[]')`), and a matrix that shrank to nothing would be a
        # coverage loss, not a saving.
        chosen = enabled
    return [{"role": e["role"], "scenario": e["scenario"]} for e in chosen]


def plan(
    entries: list[dict[str, Any]],
    root: Path,
    changes: list[str] | None,
    ci_changed: bool,
) -> dict[str, Any]:
    """Entry point shared by the CLI and the tests."""
    problems = check_consistency(entries, root)
    if problems:
        raise SystemExit("molecule plan: " + "; ".join(problems))

    if ci_changed or changes is None:
        mode, affected = "all", set()
    else:
        mode, affected = classify(changes, roles_on_disk(root))
    return {"include": select(entries, mode, affected)}


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def parse_changes(raw: str) -> list[str]:
    """paths-filter emits a JSON array; tolerate a blank/absent output."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"molecule plan: --changed-files-json is not JSON: {exc}") from exc
    if not isinstance(value, list):
        raise SystemExit("molecule plan: --changed-files-json must be a JSON array")
    return [str(v) for v in value]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--changed-files-json", default="",
                    help="JSON array of changed paths (paths-filter list-files output)")
    ap.add_argument("--ci-changed", default="false", help="'true' when .github/** changed")
    ap.add_argument("--all", action="store_true", help="ignore changes, emit every enabled entry")
    ap.add_argument("--github-output", type=Path, default=None,
                    help="append `include=<json>` to this file ($GITHUB_OUTPUT)")
    args = ap.parse_args(argv)

    entries = load_manifest(args.manifest)
    changes = None if args.all else parse_changes(args.changed_files_json)
    matrix = plan(entries, args.repo_root, changes, args.ci_changed.strip().lower() == "true")
    payload = json.dumps(matrix)

    print(f"molecule plan: {len(matrix['include'])} scenario(s)")
    for entry in matrix["include"]:
        print(f"  - {entry['role']}/{entry['scenario']}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"include={payload}\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
