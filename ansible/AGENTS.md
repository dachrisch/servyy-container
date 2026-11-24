# ansible/ — deployment automation

All production and test changes go through this directory. Container names, service
registration lists and per-host enablement all live here; a missing entry usually means
a silently skipped deploy or a stale alert, not an error.

**Start here:** build/lint/test commands and code style are in the
[root AGENTS.md](../AGENTS.md) — they are not repeated here.

## Ansible Structure

```
ansible/
├── servyy.yml              # Main playbook
├── servyy.sh / servyy-test.sh
├── inventory/production    # Defines servers and their enabled services
└── plays/
    ├── system.yml          # OS, fail2ban, monit, backups
    ├── user.yml            # Docker services, containers
    └── roles/{system,user,testing,docker_service,ls_*}/
```

**Inventory File: `ansible/production`**
- Defines all servers (servy.lehel.xyz, codey.lehel.xyz, aqui.fritz.box, etc.)
- Each server has `services_enabled:` dict specifying which services run there
- Services NOT in enabled list are skipped during deployment
- Example: opencode only enabled on codey.lehel.xyz, not on servy.lehel.xyz

**Common Tags:**
- `system` - OS packages, fail2ban, monit
- `docker` - Docker services only
- `fail2ban` - fail2ban configuration
- `backup` - Backup timers
- `user.docker.env` - Regenerate .env files
- `user.docker.{service}` - Deploy specific service (e.g., `user.docker.opencode`)

## Molecule Testing (REQUIRED FOR NEW FEATURES)

**Before implementing new Ansible features, you MUST add Molecule tests.**

### Why Test-First Matters

1. **Validation**: Proves your changes work before production deployment
2. **CI Integration**: All tests run automatically on every push
3. **Regression Prevention**: Ensures existing functionality isn't broken
4. **Documentation**: Tests show how roles are meant to be used

### Standard Workflow for New Features

```
1. PLAN: Design the feature and required test coverage
2. TEST: Create/update Molecule scenario on servyy-test
3. IMPLEMENT: Write code until test passes
4. INTEGRATE: Add scenario to CI matrix
5. DOCUMENT: Update history/YYYY-MM-DD_*.md
```

**Current Coverage**: 8 scenarios across system/testing/user/docker_service roles
**Test Environment**: servyy-test.lxd (validates before CI)
**CI Platform**: GitHub Actions (runs all scenarios in parallel)

### Key Testing Principles

**1. Test on servyy-test BEFORE CI**
- Real LXD environment with Docker
- Catches issues CI won't (permissions, networking, etc.)
- Faster iteration than waiting for CI

**2. Handle Docker Container Limitations**
- Some tasks can't work in containers (systemd timers, hardware access)
- Use conditional execution: `when: ansible_virtualization_type != 'docker'`
- Tag untestable tasks: `molecule-notest`
- Mock infrastructure dependencies (storagebox, restic, etc.)

**3. Use include_role Pattern**
- Templates need proper resolution
- Pattern: `include_role` with role name (not path) — set `ANSIBLE_ROLES_PATH` in molecule.yml provisioner env
- Never use path-based role names (`{{ playbook_dir }}/../../`) — ansible-lint flags these and they break in CI
- Set `ANSIBLE_ROLES_PATH: "${MOLECULE_PROJECT_DIRECTORY}/.."` so the role is discoverable by name

**4. Verify What Was Actually Configured**
- Don't test skipped tasks
- Check file existence and content
- Validate service states where possible

### Examples

**See existing scenarios**:
- `ansible/plays/roles/system/molecule/` - System configuration
- `ansible/plays/roles/testing/molecule/` - Development utilities
- `ansible/plays/roles/user/molecule/` - User environment setup
- `ansible/plays/roles/docker_service/molecule/` - Generic Docker service role

**Reference documentation**:
- `history/2026-01-05_molecule-testing-validation.md` - Complete validation report
- `.github/molecule-matrix.yml` - which scenarios exist and which run on every ansible change
- `.github/workflows/README.md` - CI jobs, path gating and the `CI Gate` required check

**Testing is not optional** - if you modify a role, update or add tests. The CI will reject PRs without test coverage.

> **CI gate:** register every scenario in `.github/molecule-matrix.yml`. Jobs are path-gated;
> `CI Gate` is the single required check, so never add a `paths:` trigger or require an
> individual job by name.
