---
name: opencode-dependency
description: Coordinate changes across opencode service and ansible infrastructure
triggers:
  - "deploy service"
  - "update ansible"
  - "both need"
  - "depends on"
  - "ansible AND"
  - "playbook AND service"
  - inter-dependency
delegates_to:
  - opencode-contribution
  - opencode-deployment
reads:
  - opencode/docker-compose.yml
  - opencode/scripts/
  - ansible/plays/roles/opencode/
  - ansible/plays/user.yml
  - ansible/production
---

# OpenCode Service & Ansible Coordination

This skill manages coordinated changes between opencode service configuration and ansible infrastructure code.

## When This Skill Activates

Use when work spans BOTH:
- Opencode project code/configuration (service-side)
- Ansible deployment automation (infrastructure-side)

**Examples:**
- "Add a new environment variable AND update ansible to deploy it"
- "Change service startup behavior AND modify ansible provisioning"
- "Add skills directory AND ensure ansible deploys them"
- "Update docker-compose AND change ansible role template"

## Isolation & Worktree Pattern

**CRITICAL RULE:** Each project gets its own isolated worktree.

```
Parent context (coordinates)
├─ worktree-1/infrastructure-container/ (ansible changes)
└─ worktree-2/some-opencode-project/ (service code changes)
```

**NEVER mix projects in same working directory.**

### Worktree Setup

```bash
# Create isolated worktree for infrastructure
git worktree add /tmp/wt-infra infrastructure-container-work-branch

# Create isolated worktree for opencode project
git worktree add /tmp/wt-opencode opencode-project-work-branch

# Work proceeds in isolation
# Then coordinate + merge
```

### Why Isolation Matters

- ✅ Clean git history (no accidental cross-project changes)
- ✅ Parallel development (two branches, two trees)
- ✅ Safe rollback (each project independent)
- ❌ Prevents: Accidentally staging wrong project's files
- ❌ Prevents: Merging infrastructure changes into project repo

## Coordination Workflow

### Phase 1: Analyze Dependencies

Ask these questions:
1. **Does ansible need to change?** (role logic, templates, vars)
2. **Does service config need to change?** (docker-compose, scripts, skills)
3. **Does opencode project code need to change?** (app logic)
4. **What's the execution order?**

**Common patterns:**
- Ansible first → Deploy changes → Test → Project uses new capability
- Project config first → Ansible detects → Deploys updated service
- Both in parallel → Coordinated deployment

### Phase 2: Plan Sequence

Decide deployment order:

**Option A: Ansible First**
```
1. Modify ansible role/playbook
2. Deploy to test environment (servyy-test.lxd)
3. Verify infrastructure changes work
4. Update service code to use new capability
5. Deploy to production
```

**Option B: Service First**
```
1. Update service code/config
2. Commit & push
3. Modify ansible to understand new config
4. Deploy both together
```

**Option C: Parallel (Both in Single Deployment)**
```
1. Modify ansible playbook
2. Update service code
3. Commit both
4. Deploy to test first
5. Verify together
6. Deploy to production
```

### Phase 3: Implementation

**Infrastructure changes (ansible side):**
```bash
cd /tmp/wt-infra/infrastructure-container/ansible
# Edit plays/roles/opencode/tasks/main.yml
# Edit plays/roles/opencode/templates/*
# Add new role invocations if needed
```

**Service changes (project side):**
```bash
cd /tmp/wt-opencode/opencode-project/
# Modify docker-compose.yml
# Update scripts/
# Modify .env template
# Update app code if needed
```

**Skills updates (coordination side):**
```bash
cd /home/cda/dev/infrastructure/container/opencode/skills/
# Update skill files to document new workflow
```

### Phase 4: Testing

**MANDATORY TEST-FIRST APPROACH:**

```bash
# 1. Deploy infrastructure changes to test environment
cd ansible
./servyy-test.sh --tags "user.docker.opencode" --limit servyy-test.lxd

# 2. Verify infrastructure deployed correctly
ssh servyy-test.lxd "docker ps | grep opencode"
ssh servyy-test.lxd "docker logs opencode.web --tail 20"

# 3. If service-side changes needed, verify they work with new infra
ssh servyy-test.lxd "docker exec opencode.web /path/to/test"

# 4. Only after test succeeds → Production deployment
```

## Common Coordination Scenarios

### Scenario 1: Add New Skills Directory

**Need:** Ansible deploys new skills files to ~/.config/opencode/skills/

```yaml
# ansible/plays/roles/opencode/tasks/main.yml
- name: Deploy OpenCode skills
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../../opencode/skills/"
    dest: "{{ opencode_skills_dir }}"
    owner: "{{ create_user }}"
    group: "{{ create_user }}"
    mode: '0644'
  vars:
    opencode_skills_dir: "{{ ('/home/', create_user, 'servyy-container/opencode/skills') | path_join }}"
  tags: [user.docker.opencode]

# (Inside container, via docker-compose volumes)
- name: Volume-mount skills into container at startup
  # docker-compose.yml volumes section
```

### Scenario 2: Update Environment Variables

**Ansible side:**
```yaml
# ansible/plays/roles/opencode/templates/docker.env.j2
OPENCODE_NEW_VAR={{ opencode_new_var }}
```

**Service side (docker-compose):**
```yaml
# opencode/docker-compose.yml
services:
  opencode:
    env_file:
      - .env
      - opencode.env  # New vars from ansible
```

### Scenario 3: Modify Startup Script

**Ansible side:**
```yaml
# ansible/plays/roles/opencode/tasks/main.yml
- name: Deploy updated startup script
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../../opencode/scripts/startup.sh"
    dest: "{{ startup_script_path }}"
    mode: '0755'
  notify: restart opencode container
```

**Service side (git repo):**
```bash
# opencode/scripts/startup.sh
#!/bin/sh
# ... updated startup logic here
```

## Testing Both Together

```bash
# After both ansible + service changes are ready:

# 1. Test infrastructure + service on test environment
cd ansible && ./servyy-test.sh --tags "user.docker.opencode"

# 2. Verify integrated behavior
ssh servyy-test.lxd "docker exec opencode.web /bin/sh -c 'test-command'"

# 3. Check service can access new infrastructure features
ssh servyy-test.lxd "docker logs opencode.web --tail 30"

# 4. Production deployment (after approval)
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit lehel.xyz

# 5. Final verification
ssh lehel.xyz "docker ps | grep opencode"
curl -I https://opencode.lehel.xyz
```

## Worktree Cleanup

After work is merged:

```bash
# Remove worktrees
git worktree remove /tmp/wt-infra
git worktree remove /tmp/wt-opencode

# Verify removed
git worktree list
```

## Common Pitfalls

- ❌ Mixing infrastructure + service changes in same directory (use worktrees)
- ❌ Not testing on test environment before production
- ❌ Forgetting ansible must restart container for config changes
- ❌ Assuming changes apply without redeploy (always run `servyy.sh`)
- ❌ Not checking if both repos must be pushed before deployment

## When to Delegate

- **To opencode-contribution:** For project-only code changes
- **To opencode-deployment:** For production diagnostics or service troubleshooting

## Deployment Commands

**Test Environment:**
```bash
cd /tmp/wt-infra/infrastructure-container/ansible
./servyy-test.sh --tags "user.docker.opencode"
```

**Production (after test passes):**
```bash
cd /tmp/wt-infra/infrastructure-container/ansible
./servyy.sh --tags "user.docker.opencode" --limit lehel.xyz
```

**Verification:**
```bash
# Both repos pushed?
git status
git log --oneline origin/master..HEAD

# Deployment succeeded?
ssh lehel.xyz "docker ps | grep opencode"
ssh lehel.xyz "docker logs opencode.web --tail 20"
```

## Key Files to Monitor

| Location | Purpose |
|----------|---------|
| `ansible/plays/roles/opencode/tasks/main.yml` | Core deployment logic |
| `ansible/plays/roles/opencode/templates/` | Generated config files |
| `opencode/docker-compose.yml` | Service definition |
| `opencode/scripts/startup.sh` | Container startup |
| `opencode/skills/` | Deployed skill definitions |
| `/home/cda/servyy-container/opencode/.env` | Runtime env on server |
