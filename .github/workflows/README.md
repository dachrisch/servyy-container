# CI/CD Pipeline Documentation

This directory contains the GitHub Actions CI/CD pipeline for the servyy-container Ansible infrastructure.

## Overview

The CI pipeline provides automated testing for Ansible playbooks, roles, and custom modules. It includes:

- **Linting**: YAML, Ansible, and Python code quality checks
- **Syntax validation**: Ansible playbook syntax checking
- **Unit tests**: Custom Ansible module tests
- **Integration tests**: Molecule tests for critical roles
- **Security**: git-crypt encryption validation

## Workflows

### `ci.yml` - Main CI Pipeline

Runs on:
- Pull requests to `master`
- Pushes to `master`

#### Jobs

**Fast-fail checks (run in parallel):**

1. **lint-yaml** - YAML syntax and formatting
   - Tool: yamllint
   - Config: `.yamllint.yml`
   - Duration: ~30 seconds

2. **lint-ansible** - Ansible best practices
   - Tool: ansible-lint
   - Config: `ansible/.ansible-lint`
   - Profile: production
   - Duration: ~1 minute

3. **lint-python** - Python code quality
   - Tools: flake8, pylint
   - Config: `ansible/.flake8`, `ansible/.pylintrc`
   - Target: `library/`, `plugins/`
   - Duration: ~30 seconds

4. **syntax-check** - Ansible syntax validation
   - Matrix: 5 playbooks tested in parallel
   - Creates mock encrypted files for testing
   - Duration: ~45 seconds per playbook

5. **git-crypt-validation** - Encryption integrity
   - Script: `.github/scripts/validate-git-crypt.sh`
   - Verifies files tracked by git-crypt remain encrypted
   - Duration: ~20 seconds

6. **test-custom-modules** - Unit tests
   - Tests: `ansible/library/tests/test_json_patch.py`
   - Framework: Python unittest
   - Duration: ~30 seconds

**Integration tests (run after lints pass):**

7. **molecule-test** - Role integration testing
   - Matrix: 6 role/scenario combinations
   - Driver: Docker
   - Runs in parallel
   - Duration: ~3-5 minutes per scenario
   - Uses caching for pip and Galaxy roles

## Test Matrix

### Molecule Scenarios

| Role | Scenario | Description |
|------|----------|-------------|
| system | default | Full system setup (packages, user, journald) |
| system | minimal | Basic user and journald only |
| system | with-docker | Docker + kernel cleanup tasks |
| user | default | Shell setup (zprezto) |
| user | docker-only | Docker network creation |
| testing | default | LXD test environment setup |

### Excluded from CI

**LeagueSphere roles** (`ls_setup`, `ls_app`, `ls_access`, `ls_db_sync`) are tested manually on `servyy-test.lxd`:
- Require encrypted production secrets
- Need SSH chroot jail setup
- Depend on real git.lehel.xyz infrastructure
- Include manual operations tagged with `never`

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

- **Lint jobs**: ~30-60 seconds each (parallel)
- **Syntax checks**: ~45 seconds per playbook (parallel)
- **Molecule tests**: ~3-5 minutes per role/scenario (parallel)
- **Total CI time**: ~8-12 minutes (with caching)

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

### Adding New Roles

When adding a new role:

1. Create `molecule/default/` directory structure
2. Add `molecule.yml`, `prepare.yml`, `converge.yml`, `verify.yml`
3. Add role to matrix in `.github/workflows/ci.yml`

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
