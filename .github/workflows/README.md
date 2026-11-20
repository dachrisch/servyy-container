# CI/CD Pipeline Documentation

This directory contains the GitHub Actions CI/CD pipeline for the servyy-container Ansible infrastructure.

## Overview

The CI pipeline provides automated testing for Ansible playbooks, roles, and custom modules. It includes:

- **Linting**: YAML, Ansible, and Python code quality checks
- **Syntax validation**: Ansible playbook syntax checking
- **Unit tests**: Custom Ansible module tests
- **Integration tests**: Molecule tests for critical roles
- **Security**: git-crypt encryption validation
- **Path-aware**: each job runs only when the paths a change touches can affect it
- **One required check**: `CI Gate` aggregates the rest (see [Path gating](#path-gating))

## Workflows

### `ci.yml` - Main CI Pipeline

Runs on:
- Pull requests to `master`
- Pushes to `master`

#### Jobs

Every job except `changes`, `git-crypt-validation` and `gate` is skipped unless the
change touches a path that can affect it. `changes` classifies the diff with
`dorny/paths-filter` and every other job reads its outputs.

| Job | Runs when | What it does |
|---|---|---|
| `changes` | always | Classifies the diff; produces the booleans and the changed `ansible/**` path list |
| `lint-yaml` | `ansible` or `ci` | yamllint over `ansible/plays` (`.yamllint.yml`) |
| `lint-ansible` | `ansible` or `ci` | ansible-lint, production profile |
| `lint-python` | `ansible`, `python`, `compose` or `ci` | flake8 + pylint on `ansible/library`, **and** `architecture/render.py --selftest` |
| `syntax-check` | `ansible` or `ci` | 5 playbooks, mock encrypted files |
| `git-crypt-validation` | **always** | no plaintext blob, no encrypted empty file |
| `test-custom-modules` | `ansible`, `python` or `ci` | 8 `unittest` suites incl. the matrix-planner tests |
| `molecule-plan` | `ansible` or `ci` | Computes this PR's molecule matrix |
| `molecule-test` | `ansible` or `ci` | The computed matrix (baseline 8 + the changed roles) |
| `gate` | **always** | `CI Gate` — the only required check |

Category paths:

| Category | Paths |
|---|---|
| `ansible` | `ansible/**`, and not `*.md` |
| `python` | `**/*.py` |
| `compose` | `**/docker-compose*.yml` |
| `ci` | `.github/**`, and not `*.md` |
| `yamllint` | `.yamllint.yml` |

The classifier runs with `predicate-quantifier: every`. That is load-bearing: under
the default `some`, a leading `!` means "a file that is **not** this", so
`!**/*.md` matched every non-markdown file and a lone
`.github/workflows/README.md` returned `ansible=true` and `ci=true` and ran the
whole suite. With `every`, one file must satisfy every pattern — "under this
path and not a doc" — which is the intended rule.

`compose` is in `lint-python`'s condition on purpose: the architecture selftest
parses every `*/docker-compose.yml`, and that is the only CI coverage a compose
edit has. Everything else (service `.env`s, `docs/`, `history/`, `*.md`, dotfile
directories) runs no heavy job — a README-only PR costs ~25 seconds.

#### Molecule matrix selection

`.github/molecule-matrix.yml` is the single source of truth for which scenarios
exist. Each entry is `baseline: true` (runs on **every** ansible change) or
`baseline: false` (runs only when its own role directory changed).

The baseline is exactly the eight contexts the master ruleset used to require by
name (`system/{minimal,core,with-docker,default}`, `testing/default`,
`user/{default,docker-only}`, `docker_service/default`), so core coverage never
depends on which files a PR happens to touch, and their check-run names are
unchanged.

`.github/scripts/molecule_matrix.py` widens to the **whole** matrix when a change
cannot be attributed to one role: shared playbooks, `ansible/plays/vars/**`,
`ansible/library/**`, `ansible/tests/**`, `ansible/requirements*.yml`, a `.github/`
change, or a role the manifest has never heard of. It also fails the build when
the manifest and `ansible/plays/roles/*/molecule/*/` disagree in either
direction — a new `molecule/<scenario>/` directory without an entry is an error,
not a scenario that silently never runs.

#### Path gating

Why the gate exists: a skipped job publishes **no check run**. If the ruleset
required individual jobs, a docs-only PR would sit at "Expected — waiting for
status" forever and could never be auto-merged. `CI Gate` always runs, reads the
real results of the jobs it needs, and passes when each is `success` or
`skipped` (fails on `failure`/`cancelled`, and prints a job→result table).

Two rules follow from that:

- **Never** put `paths:` on the `on:` trigger. The workflow would then not report
  at all for a docs-only PR and the required check would hang instead of passing.
- **Never** make an individual job or matrix entry the required check. Add the
  job to `gate`'s `needs` list instead; the ruleset needs no edit, and it no
  longer drifts (it used to require 8 of 16 molecule entries).

#### Excluded from CI

**LeagueSphere roles** (`ls_setup`, `ls_app`, `ls_access`, `ls_db_sync`) are tested manually on `servyy-test.lxd`:
- Require encrypted production secrets
- Need SSH chroot jail setup
- Depend on real git.lehel.xyz infrastructure
- Include manual operations tagged with `never`

**`portainer_rbac/default`** is registered in the manifest with `enabled: false`
(it stands up a real Portainer in `prepare.yml`). The `reason` is mandatory, so
an excluded scenario is always explained rather than merely absent.

## Running Tests Locally

### Prerequisites

```bash
# Install dependencies
pip install -r ansible/requirements.txt
pip install molecule molecule-plugins[docker] docker

# Install Ansible Galaxy roles
ansible-galaxy install -r ansible/requirements.yml

# Ensure Docker is running
docker ps
```

### Lint Tests

```bash
# YAML linting
yamllint ansible/

# Ansible linting
cd ansible && ansible-lint

# Python linting
cd ansible
flake8 library/ plugins/ --max-line-length=120
pylint library/json_patch.py --disable=C0103,R0912,R0915
```

### Syntax Check

```bash
# Check all playbooks
cd ansible
for playbook in servyy.yml plays/*.yml; do
  ansible-playbook $playbook --syntax-check -i testing
done
```

### Custom Module Tests

```bash
cd ansible/library
python -m unittest discover -s tests -p "test_*.py" -v
```

### git-crypt Validation

```bash
./.github/scripts/validate-git-crypt.sh
```

### Molecule Tests

```bash
# Test a specific role/scenario
cd ansible/plays/roles/system
molecule test --scenario-name default

# Test all scenarios for a role
molecule test --all

# Useful Molecule commands
molecule create          # Create test instance
molecule converge        # Run playbook
molecule verify          # Run verification tests
molecule login           # SSH into test instance
molecule destroy         # Clean up test instance
```

## Caching Strategy

The CI uses GitHub Actions caching to speed up runs:

- **pip packages**: `~/.cache/pip` (keyed by `requirements.txt`)
- **Ansible Galaxy roles**: `~/.ansible/roles` (keyed by `requirements.yml`)

Cache hits reduce CI time from ~12 minutes to ~8 minutes.

## Mock Data for Encrypted Files

CI cannot decrypt git-crypt files (by design). The `syntax-check` job creates mock files with the same structure:

```yaml
# Mock secrets.yml
storagebox_credentials:
  host: "mock.example.com"
  share: "backup"
  user: "mockuser"
  pass: "mockpass"

# Mock secret_leaguesphere.yaml
ls:
  user: lsuser
ssh_chroot_jail_path: /test/jail
```

This allows syntax checking without exposing real secrets.

## Troubleshooting

### Linting Failures

**Issue:** ansible-lint errors

**Solution:**
```bash
# Run locally to see detailed errors
cd ansible && ansible-lint --show-relpath
```

### Molecule Test Failures

**Issue:** Container fails to start

**Solution:**
```bash
# Check Docker daemon is running
docker ps

# Increase logging verbosity
molecule --debug test
```

**Issue:** Task fails in Molecule but works in production

**Cause:** Mock variables or skipped dependencies

**Solution:** Review `converge.yml` for skipped tasks

### Syntax Check Failures

**Issue:** Missing variables in mock files

**Solution:** Update mock files in `ci.yml` syntax-check job

### git-crypt Validation Failures

**Issue:** File not tracked by git-crypt

**Solution:** Check `.gitattributes` patterns

## Performance Expectations

Path gating means the cost follows the change, not the repository:

| Change touches | Jobs | Wall clock |
|---|---|---|
| `*.md`, `docs/`, `history/`, dotfiles | `git-crypt-validation`, `gate` | ~25 s |
| a `*/docker-compose.yml` | + `lint-python` (selftest) | ~45 s |
| one role under `ansible/plays/roles/` | + lints, syntax, tests, baseline + that role's molecule | ~6-8 min |
| shared ansible paths, `.github/**`, `ansible/library/**` | everything (all 16 scenarios) | ~8-12 min |

`molecule-test` uses `fail-fast: false`, so one broken scenario does not hide the
rest of the matrix. Concurrency group `ci-<PR or ref>` cancels a superseded PR run
instead of running both.

## CI vs Manual Testing

**CI does NOT replace manual testing on `servyy-test.lxd`!**

Always follow the test-first deployment policy:
1. Develop changes in git
2. **Test on `servyy-test.lxd` using `./servyy-test.sh`**
3. Get explicit user approval
4. Deploy to production using `./servyy.sh`

CI adds quality gates but cannot test:
- Real infrastructure dependencies
- Full service deployments
- LeagueSphere roles
- Production-specific configurations

## Maintenance

### Adding a molecule scenario

1. Create `ansible/plays/roles/<role>/molecule/<scenario>/` with `molecule.yml`,
   `prepare.yml`, `converge.yml` and `verify.yml`
2. Add **one line** to `.github/molecule-matrix.yml`:

   ```yaml
   - {role: <role>, scenario: <scenario>, baseline: false}
   ```

   Use `baseline: true` only if the scenario must run on every ansible change.
   Add `enabled: false` plus a `reason` to register a scenario CI must not run.
3. Nothing else — `ci.yml` reads the manifest, there is no matrix to edit.

CI fails when the directory and the manifest disagree (either direction), so a
forgotten line cannot turn into a scenario that silently never runs. Locally:

```bash
cd ansible/tests/ci_matrix && python -m unittest -v test_molecule_matrix
python3 .github/scripts/molecule_matrix.py --all        # the full matrix
python3 .github/scripts/molecule_matrix.py \
  --changed-files-json '["ansible/plays/roles/restic/tasks/main.yml"]'
```

### Updating Dependencies

```bash
# Update Python packages
cd ansible
pip freeze > requirements.txt

# Update Ansible Galaxy roles
ansible-galaxy install --force -r requirements.yml
```

### Updating Linting Rules

Edit configuration files:
- `.yamllint.yml` - YAML rules
- `ansible/.ansible-lint` - Ansible rules
- `ansible/.flake8` - Python flake8 rules
- `ansible/.pylintrc` - Python pylint rules

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Molecule Documentation](https://molecule.readthedocs.io/)
- [ansible-lint Documentation](https://ansible-lint.readthedocs.io/)
- [yamllint Documentation](https://yamllint.readthedocs.io/)
- [git-crypt Documentation](https://github.com/AGWA/git-crypt)
