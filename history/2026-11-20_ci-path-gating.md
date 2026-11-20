# Path-gated CI, one required check: `CI Gate` (2026-11-20)

Branch `ci/path-gating` from master, PR [#316](https://github.com/dachrisch/servyy-container/pull/316).

## The problem

Every PR paid for the whole suite — four lint jobs, a five-playbook syntax
matrix, six unit suites and **sixteen** molecule scenarios (~12 min) — whether
it touched a role or fixed a typo in a README.

Two things stood in the way of just making jobs conditional:

1. **A skipped job publishes no check run.** The master ruleset required nine
   contexts by name, so a path-gated job would leave its required check at
   "Expected — waiting for status" forever, and a docs-only PR could never be
   auto-merged — which is what Renovate needs.
2. **The required list had already drifted.** It named 8 molecule entries while
   the matrix ran 16, and `portainer_rbac/molecule/default/` existed on disk
   without ever running anywhere. A per-job required list requires a ruleset
   edit every time a job is added or renamed.

## What changed

### `changes` — classify the diff once

`dorny/paths-filter@v3` twice: once for booleans, once with `list-files: json`
for the actual `ansible/**` paths (the list lands in `<filter>_files`, not in
the filter's own output — the first run failed on exactly that, see below).
`fetch-depth: 0` because a push event diffs `before`..`after` and needs both
commits; job-level `permissions` has to re-grant `contents: read` alongside
`pull-requests: read`, or checkout has no token.

| Category | Paths |
|---|---|
| `ansible` | `ansible/**` minus `*.md`, `.yamllint.yml` |
| `python` | `**/*.py` |
| `compose` | `**/docker-compose*.yml` |
| `ci` | `.github/**` minus `*.md` |

### Jobs follow the categories

| Job | Condition |
|---|---|
| `git-crypt-validation` | **always** — a docs-only PR is exactly how a secret lands in a `.md` |
| `lint-yaml`, `lint-ansible`, `syntax-check` | `ansible or ci` |
| `lint-python` (+ `render.py --selftest`) | `ansible or python or compose or ci` |
| `test-custom-modules` | `ansible or python or ci` |
| `molecule-plan`, `molecule-test` | `ansible or ci` |
| `gate` | **always** |

`compose` is in `lint-python` on purpose: `architecture/render.py --selftest`
parses every `*/docker-compose.yml`, so it is the only CI coverage a compose
edit has (measured: 12 s).

### The matrix moved to `.github/molecule-matrix.yml`

Every scenario on disk is registered once. `baseline: true` runs on **every**
ansible change; that set is exactly the eight contexts the ruleset required, so
core coverage cannot shrink with the diff and their check-run names are
unchanged — the old ruleset kept passing while this landed. `baseline: false`
runs only when that role's own directory changed. `enabled: false` requires a
`reason`, which is how `portainer_rbac/default` is now recorded instead of
silently never running. The file is `.yml`: `.gitattributes` encrypts `*.yaml`,
and CI cannot read a git-crypt blob.

`.github/scripts/molecule_matrix.py` computes it and **widens to everything**
when a change cannot be attributed to one role: shared playbooks,
`ansible/plays/vars/**`, `ansible/library/**`, `ansible/tests/**`,
`ansible/requirements*.yml`, a `.github/` change, or a role the manifest has
never heard of. It also cross-checks manifest ↔ `roles/*/molecule/*/` in both
directions and fails otherwise, so the drift that hid `portainer_rbac` cannot
recur.

Two GitHub Actions details are load-bearing and commented in the workflow: a
skipped job publishes no outputs, so `fromJSON('')` needs a sentinel fallback,
and an empty matrix is a fatal error rather than a skip — the planner therefore
never emits one (the baseline guarantees ≥ 8 entries).

### `CI Gate`

`if: always()`, needs every job, parses `toJSON(needs)` in python3: passes when
each result is `success` or `skipped`, fails on `failure`/`cancelled`, and
prints a job→result table. This is the only context the ruleset needs, so
adding or renaming a job no longer touches branch protection.

Also added: `concurrency: ci-<PR number or ref>` with `cancel-in-progress` only
for PRs, so a force-push does not run two suites.

## Files changed

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | `changes`, `molecule-plan`, `gate` jobs; conditions on the rest; dynamic matrix; concurrency |
| `.github/molecule-matrix.yml` | new — the single source of truth for scenarios, with baseline flags |
| `.github/scripts/molecule_matrix.py` | new — classification, widening, consistency check, matrix emission |
| `ansible/tests/ci_matrix/test_molecule_matrix.py` | new — 24 tests, run by `test-custom-modules` |
| `.github/workflows/README.md` | jobs/triggers table, path-gating rationale, how to add a scenario |
| `.claude/skills/manage-service/SKILL.md` | "Adding Role to CI" now points at the manifest (it documented a matrix shape that never existed) |
| `AGENTS.md` | testing requirements: register the scenario, never require a job by name |
| ruleset `21452638` | nine required contexts → `CI Gate` |

## Verification

Local:

```bash
cd ansible/tests/ci_matrix && python -m unittest -v test_molecule_matrix   # 24 OK
python3 .github/scripts/molecule_matrix.py --all                           # 16 scenarios
python3 .github/scripts/molecule_matrix.py \
  --changed-files-json '["ansible/plays/roles/restic/tasks/main.yml"]'     # 8 baseline + restic ×2
```

CI, PR #316 (touches `.github/**` and `ansible/tests/**`, so it must run the
full suite — the self-test):

| Check | Result |
|---|---|
| `Detect changed paths` | 10 s, all four categories true |
| `Plan Molecule Matrix` | 8 s, 16 scenarios |
| `Lint Python` (incl. selftest) | 12 s |
| `Validate git-crypt Encryption` | 14 s |
| `Lint YAML` / syntax matrix | 11 s / 35–45 s each |
| `CI Gate` | green, table of 9 results |
| molecule matrix | 16/16 |

First run failed and is kept here because the fix is a trap worth remembering:
`list-files: json` publishes the list to `<filter>_files`, while the filter's
own output remains the boolean. The job read `ansible` (value `true`) and the
planner rejected it with `must be a JSON array, got 'true'` — `8aaaa8b` renames
the filter and makes that error name the value it received.

After merge: ruleset `21452638` required `CI Gate` only; a docs-only PR reported
`Validate git-crypt Encryption` + `CI Gate` and was mergeable without a single
molecule run.

## Ordering (why this could land without blocking anything)

The baseline keeps the eight formerly required check names, so the old ruleset
passed on this PR's own runs. The ruleset flip came **after** the merge: a PR
opened before the flip whose head branch does not contain `gate` would not
report `CI Gate`, so it needs a push or a re-run rather than a `--admin` merge.

## Rejected alternatives

- **`on.pull_request.paths`** — the workflow then does not report at all for a
  docs-only PR, and a required check hangs instead of passing.
- **Requiring individual jobs / matrix entries** — the drift and deadlock above.
- **Registering `portainer_rbac/default` and running it** — `prepare.yml` stands
  up a real Portainer inside the container. It is registered `enabled: false`
  with that reason; flipping one boolean turns it on if it earns its minutes.
