# AGENTS.md - Infrastructure Container Development Guide


## Subdirectory guides

Each subdirectory with real complexity has its own guide. Read the relevant one before
changing that component; this file holds only repo-wide rules.

| Guide | Covers |
|---|---|
| [ansible/AGENTS.md](ansible/AGENTS.md) | Playbooks, inventory, tags, Molecule testing and CI matrix |
| [architecture/AGENTS.md](architecture/AGENTS.md) | `landscape.yaml` / `render.py` service map |
| [ci/AGENTS.md](ci/AGENTS.md) | Forgejo Git + Actions at ci.lehel.xyz |
| [claude-hub/AGENTS.md](claude-hub/AGENTS.md) | Headless Claude Code session dispatcher |
| [docs/AGENTS.md](docs/AGENTS.md) | Durable reference docs, LeagueSphere environments |
| [hetzner/AGENTS.md](hetzner/AGENTS.md) | Hetzner firewall rules from a dynamic client IP |
| [history/AGENTS.md](history/AGENTS.md) | Change records; plans are temporary |
| [monitor/AGENTS.md](monitor/AGENTS.md) | Prometheus, Grafana, Loki, fail2ban, log queries |
| [moodle/AGENTS.md](moodle/AGENTS.md) | OFFD / Flag Academy Moodle platform |
| [opencode/AGENTS.md](opencode/AGENTS.md) | OpenCode service on codey, cross-server SSH |
| [opencode/scripts/AGENTS.md](opencode/scripts/AGENTS.md) | Global instructions deployed into the container |
| [renovate/AGENTS.md](renovate/AGENTS.md) | Self-hosted Renovate updater |
| [runny/AGENTS.md](runny/AGENTS.md) | Forgejo Actions runner (codey + runny) |
| [scripts/AGENTS.md](scripts/AGENTS.md) | Host-side scripts, cleanup timers |
| [searxng/AGENTS.md](searxng/AGENTS.md) | Private search frontend |
| [traefik/AGENTS.md](traefik/AGENTS.md) | Routing, TLS, branded error pages |
| [achim-hoefer/AGENTS.md](achim-hoefer/AGENTS.md) | Static site for höfer-architekten.de |


This file contains build/lint/test commands and code style guidelines for agentic coding agents working in this repository.

## Build/Lint/Test Commands

### Ansible Development
```bash
# Syntax check all playbooks
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/system.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/user.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/testing.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/leaguesphere.yml --syntax-check -i testing

# Lint Ansible playbooks
cd ansible && ansible-lint --force-color --show-relpath

# Molecule Testing (REQUIRED for new features)
cd ansible/plays/roles/{role}/ && molecule test --scenario-name {scenario}

# Available scenarios:
# system: minimal, core, with-docker, default
# user: default, docker-only  
# testing: default

# Run all scenarios in parallel
cd ansible && molecule test

# Single test example
cd ansible/plays/roles/system && molecule test --scenario-name minimal
```

Full Molecule workflow, scenarios and CI matrix rules: [ansible/AGENTS.md](ansible/AGENTS.md).

### Python Development (Custom Modules)
```bash
# Install dependencies
cd ansible && pip install -r requirements.txt

# Lint Python code
cd ansible && flake8 library/ --max-line-length=120
cd ansible && pylint library/json_patch.py --disable=C0103,R0912,R0915,C0209,W0613,R1705,W0707,R1720,R1710,W0612,R0911,C0116,R1735 --fail-under=6.0

# Run unit tests
cd ansible/library && python -m unittest discover -s tests -p "test_*.py" -v
```

### YAML Development
```bash
# Lint YAML files
cd ansible && yamllint -c ../.yamllint.yml .
```

### Docker Development
```bash
# Build and test docker-compose services
cd {service} && docker-compose config --quiet
cd {service} && docker-compose up --build --no-start
```

## Code Style Guidelines

### General Principles
- **Test-First Development**: Always write Molecule tests before implementing new Ansible features
- **Security First**: Never commit unencrypted secrets or credentials
- **Idempotency**: All Ansible tasks must be idempotent
- **Documentation**: Update history/YYYY-MM-DD_description.md for major changes; plans are deleted when the job is done (rules: [history/AGENTS.md](history/AGENTS.md))

### Ansible Style
```yaml
# Use 2-space indentation
- name: Descriptive task name
  module_name:
    key: value
  register: task_output
  tags:
    - appropriate.tag
  when: condition | default(false)
  notify: handler_name

# Use include_tasks over import_tasks for dynamic includes
- include_tasks: tasks/file.yml
  vars:
    custom_var: value
  tags:
    - dynamic.tag
```

### YAML Formatting
- Max line length: 160 characters (warning level)
- 2-space indentation
- Consistent sequence indentation
- Use comments sparingly, 1 space from content
- Document start (---) optional for single-document files

### Python Style (Custom Modules)
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Module docstring explaining purpose."""

import json
import os
import sys
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

class ExampleClass:
    """Class docstring explaining purpose."""
    
    def __init__(self, param):
        """Initialize with parameters."""
        self.param = param
        self._private_var = None
    
    def public_method(self):
        """Public method description."""
        return self.param
    
    def _private_method(self):
        """Private method description."""
        return self._private_var
```

### Naming Conventions
- **Files**: kebab-case (e.g., `docker_services.yml`, `json_patch.py`)
- **Variables**: snake_case (e.g., `create_user`, `docker_services`)
- **Functions/Methods**: snake_case with descriptive names
- **Classes**: PascalCase (e.g., `JSONPatcher`, `PatchManager`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `ANSIBLE_METADATA`, `DOCUMENTATION`)
- **Tags**: kebab-case with descriptive names (e.g., `user.docker.services`)

### Error Handling
```yaml
# Ansible tasks should handle errors gracefully
- name: Task with error handling
  module_name:
    key: value
  register: result
  ignore_errors: yes  # Only when appropriate
  failed_when: result.failed and 'specific_error' not in result.msg
  changed_when: result.changed
```

```python
# Python error handling
class CustomError(Exception):
    """Custom exception class."""
    pass

def risky_operation():
    try:
        # Operation that might fail
        result = some_function()
        return result
    except SpecificError as e:
        # Handle specific error
        raise CustomError(f"Operation failed: {e}") from e
    except Exception as e:
        # General error handling
        raise CustomError(f"Unexpected error: {e}") from e
```

### Import Organization
```python
# Standard library imports first
import json
import os
import sys
import unittest

# Third-party imports next
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes, to_native

# Local imports last
from json_patch import JSONPatcher
```

### Documentation Standards
```yaml
# Ansible tasks should have clear documentation
- name: Configure system packages
  apt:
    name: "{{ packages }}"
    state: present
  vars:
    packages:
      - nginx
      - fail2ban
  tags:
    - system.packages
  when: ansible_os_family == 'Debian'
  notify: restart nginx
  
  # Add comments for complex logic
  # This task installs essential security packages
  # and notifies handlers for service restarts
```

### Git Workflow
```bash
# Feature branch naming
git checkout -b claude/feature-name

# Commit message format
feat: add new service deployment
git commit -m "feat: description"

# Before production deployment
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh

# After successful test deployment
cd ansible && ./servyy.sh --limit servy.lehel.xyz
```

### Security Guidelines
- **Never** commit unencrypted secrets
- **Always** use git-crypt for encrypted files
- **Validate** git-crypt status before committing: `git-crypt status`
- **Use** environment variables for sensitive configuration
- **Follow** principle of least privilege for all service accounts

### Testing Requirements
- **Molecule tests required** for all new Ansible features
- **Register every molecule scenario** in `.github/molecule-matrix.yml` — CI fails if the scenarios on disk and the manifest disagree. Jobs are path-gated; `CI Gate` is the single required check, so never add a `paths:` trigger or require an individual job by name (see [.github/workflows/README.md](.github/workflows/README.md#path-gating))
- **Unit tests required** for all custom Python modules
- **Integration tests** for complex service deployments
- **Test on servyy-test.lxd** before production deployment
- **CI validation** must pass before merging

### Performance Considerations
- Use `async` and `poll` for long-running tasks
- Implement proper error handling and retries
- Use `check_mode` for read-only operations
- Optimize Docker image sizes and service configurations
- Monitor resource usage with Prometheus/Grafana stack

### Docker Service Guidelines
```yaml
# Service configuration standards
services:
  app:
    container_name: ${COMPOSE_PROJECT_NAME}.app
    image: image:tag
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
    environment:
      - KEY=value
    volumes:
      - type: bind
        source: ./data
        target: /app/data
        read_only: true
```

### Emergency Procedures
- **Never** make manual changes to production servers
- **Always** replicate manual changes in git repo
- **Test** emergency fixes on test environment first
- **Document** all emergency procedures in history logs
- **Follow** standard deployment workflow after emergency fixes

## Critical Paths
- **Ansible playbooks**: `ansible/servyy.yml`, `ansible/plays/*.yml`
- **Encrypted files**: `ansible/plays/vars/secrets.yml`, `ansible/plays/vars/secret_*.yaml`
- **Custom modules**: `ansible/library/`, `ansible/library/tests/`
- **Docker services**: `*/docker-compose.yml`
- **Molecule tests**: `ansible/plays/roles/*/molecule/`
- **DevHub**: `devhub/docker-compose.yml`, `ansible/plays/roles/docker_service/templates/devhub/`

## Validation Commands
```bash
# Pre-commit validation
git-crypt status
ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && yamllint -c ../.yamllint.yml .
cd ansible && flake8 library/ --max-line-length=120
cd ansible/library && python -m unittest discover -s tests -p "test_*.py" -v

# LeagueSphere Demo Verification
ssh lehel.xyz "docker ps | grep leaguesphere-demo"                    # Verify demo containers running
ssh lehel.xyz "curl -s https://demo.leaguesphere.app/health/ | head"  # Check API health
ssh lehel.xyz "docker logs portainer.ofelia | grep demo-reset"        # Verify Ofelia scheduler
# Manual reset verification (if needed)
ssh lehel.xyz "docker exec leaguesphere-demo.demo-app /bin/bash -c 'rm -f /app/.demo_last_reset && /app/entrypoint.demo.sh'"

# DevHub Verification
ssh codey.lehel.xyz "docker ps | grep devhub"                        # Verify devhub containers running
ssh codey.lehel.xyz "curl -s https://devhub.lehel.xyz/api/auth/me"   # Check auth endpoint
ssh codey.lehel.xyz "docker logs devhub.web"                         # Check app logs
```

## Specialized Agents Available

**Service Infrastructure Agents** (`.claude/agents/`):
- `service-master` - Deploy, troubleshoot, manage Docker services and Traefik routing
- `service-requirements-analyst` - Plan new service deployments with requirements analysis
- `service-tester` - Pre-production testing on servyy-test.lxd before production
- `dns-master` - Manage DNS infrastructure via Porkbun API, validate DNS changes

**When to use dns-master agent:**
- Query current DNS records for lehel.xyz
- Create/update/delete DNS entries
- Validate DNS architecture changes
- Restructure DNS layout
- Troubleshoot DNS resolution issues
- Design Ansible-integrated DNS management

**Example:**
```
You: "Add DNS records for new service"
Agent: dns-master (query current state → validate → create → verify)
Result: New service accessible via DNS
```

## Notes for Agents
- This is a **production infrastructure** repository - changes have real-world impact
- **Test-first approach** is mandatory for all infrastructure changes
- **Security** is paramount - never compromise encryption or access controls
- **Documentation** is critical - update history logs for all significant changes
- **DNS changes affect all users** - Always validate and test before applying to production
- **Rollback procedures** should be considered for all major deployments

## Repository operations

## Quick Commands

```bash
# Production deployment (all servers with their enabled services)
cd ansible && ./servyy.sh

# Test deployment
cd scripts && ./setup_test_container.sh && cd ../ansible && ./servyy-test.sh

# Deploy to specific server only
cd ansible && ./servyy.sh --limit servy.lehel.xyz      # Primary server
cd ansible && ./servyy.sh --limit codey.lehel.xyz     # Opencode server

# Deploy specific service to its server
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit codey.lehel.xyz
cd ansible && ./servyy.sh --tags "user.docker.monitor" --limit servy.lehel.xyz

# Remove a service (interactive, with confirmation)
cd ansible && ansible-playbook plays/remove_service.yml -e "target_host=servy.lehel.xyz"

# Recreate locked Restic repositories (DESTRUCTIVE)
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags restic.recreate

# Service management (know which server has the service!)
ssh lehel.xyz "docker ps"                          # Check containers on lehel.xyz
ssh code.lehel "docker ps"                         # Check containers on code.lehel
ssh {server} "docker logs {container} --tail 50"   # View logs on specific server
ssh {server} "docker restart {container}"          # Restart on specific server
```

⚠️ **CRITICAL:** Always use `--limit {server}` to target the correct server!


## DNS Management

The infrastructure uses **Porkbun** for DNS management on `lehel.xyz` domain via the `dns-master` agent.

### DNS Architecture

```
lehel.xyz (root domain)
  ├─ ALIAS → servy.lehel.xyz (primary server)
  │
  ├─ servy.lehel.xyz (primary server: 49.13.6.173 / 2a01:4f8:c013:f6f4::1)
  │  └─ *.lehel.xyz → CNAME → servy.lehel.xyz
  │     (wildcard catches all lehel services: git, photoprism, etc.)
  │
  └─ codey.lehel.xyz (secondary server: 138.2.180.191 /
  │  2603:c020:802e:5f01:0:876f:f045:3504 — Oracle A1)
     └─ code.lehel.xyz → CNAME → codey.lehel.xyz (public alias)
        (codey infrastructure detail is hidden from users)
```

**Explicit names that override the wildcard:**

| Name | Points at | Why |
|---|---|---|
| `monitor.lehel.xyz` | codey | Grafana moved there 2026-11-20 (alerting survives a servy outage). |
| `loki.lehel.xyz` | codey | Loki's authenticated ingest/query route (basicAuth + ipAllowList; servy pushes its logs here). |
| `prometheus.lehel.xyz` | **servy** (wildcard, no explicit record) | Prometheus stayed on servy; codey's Grafana queries it through this authenticated route. |

**Key points:**
- `codey.lehel.xyz` is the internal server name (not exposed to users)
- `code.lehel.xyz` is the public alias users access (backward compatible)
- Wildcard `*.lehel.xyz` handles all lehel services (git, photoprism, monitor, etc.)
- Each server has Traefik that routes requests to correct containers

### DNS Management Tasks

**Use the `dns-master` agent for all DNS operations:**

```bash
# Query current DNS records
# (agent will show all records for lehel.xyz, organized by type)

# Create new DNS record
# (agent validates, shows impact, gets your approval)

# Update existing record
# (agent queries current state, shows diff, executes change)

# Delete DNS record
# (agent confirms what will be removed, shows impact)

# Restructure DNS
# (agent designs plan, validates changes, applies safely)
```

**Example workflow:**
```
You: "Add DNS entry for new service xyz on lehel.xyz"
Agent: "I'll create xyz.lehel.xyz as CNAME → servy.lehel.xyz"
Agent: "Verifying no conflicts... checking Traefik config..."
Agent: "Ready to create. Approve? [yes/no]"
You: "yes"
Agent: "✓ Created xyz.lehel.xyz → servy.lehel.xyz"
Agent: "✓ Verified DNS resolves correctly"
Agent: "✓ Service will be accessible at xyz.lehel.xyz"
```

### DNS Credentials

Porkbun API keys stored in: `ansible/plays/vars/secrets.yml` (git-crypt encrypted),
as one entry per Porkbun account under `porkbun:`, keyed by the account name the
API reports on `/ping`:
- `porkbun.dachrisch.pk` / `porkbun.dachrisch.sk` — main account: `lehel.xyz`,
  `xn--hfer-architekten-mwb.de`. This is the account that pays for renewals and
  transfers.
- `porkbun.bumbledomain.pk` / `porkbun.bumbledomain.sk` — `bumbleflies.de` only
  (moved into its own account 2026-11-18). Never used for purchases.

A key only sees its own account's domains — the wrong one returns
`DOMAIN_NOT_FOUND` / `INVALID_DOMAIN`, which is also how DNS-01 fails silently.
`scripts/dns-layout.sh` takes `PORKBUN_ACCOUNT=<name>` (default `dachrisch`).

Only the `dns-master` agent needs these credentials. Credentials are:
- ✅ Encrypted with git-crypt (safe in git)
- ✅ Never exposed in logs or output
- ✅ Only used by dns-master agent for Porkbun API calls

### Porkbun API Reference

**Endpoints used:**
- `GET /api/json/v3/dns/retrieve/{domain}` - List all DNS records
- `POST /api/json/v3/dns/create/{domain}` - Create record
- `POST /api/json/v3/dns/edit/{domain}/{id}` - Update record
- `POST /api/json/v3/dns/delete/{domain}/{id}` - Delete record

**Full API docs:** https://porkbun.com/api/json/v3/documentation

### Common DNS Patterns

**Service on lehel (primary server):**
```
{service}.lehel.xyz → CNAME → servy.lehel.xyz
Example: git.lehel.xyz → CNAME → servy.lehel.xyz
```

**Service on code (secondary server):**
```
code.lehel.xyz → CNAME → codey.lehel.xyz
(Service-specific routing handled by Traefik, not DNS)
```

**Adding a new explicit DNS entry:**
```
{service}.lehel.xyz → CNAME → servy.lehel.xyz
(or use Traefik labels in docker-compose if CNAME not needed)
```

### Troubleshooting DNS Issues

**Service not accessible after DNS change:**
1. Verify record in Porkbun: `dns-master agent` → "Show current DNS"
2. Check DNS propagation: `dig {service}.lehel.xyz`
3. Verify Traefik routing: `ssh lehel.xyz "docker logs traefik.traefik | grep {service}"`
4. Check certificate: `ssl-verify {service}.lehel.xyz` (ACME must have valid cert)
5. Revert if needed: `dns-master agent` → "Restore DNS to previous state"

**DNS resolves but service returns 502:**
- Traefik routing issue (not DNS)
- Check: `docker ps | grep {service}` on correct server
- Check: Service Traefik labels match DNS entry hostname
- Restart Traefik if needed: `docker restart traefik.traefik`

**Changes not propagating:**
- TTL (time-to-live) may be high (default: 600 seconds)
- Clear local DNS cache: `systemctl restart systemd-resolved`
- Test from multiple nameservers: `dig @8.8.8.8 {service}.lehel.xyz`
- Wait 5-10 minutes for global propagation


## SSH Key-Based Access Setup

**SSH access between servers is configured automatically by Ansible roles.**

### How It Works

**For user workstation → server access:**
1. System role creates the `cda` user on both production servers
2. Copies your local SSH public key (`~/.ssh/id_rsa.pub`) to each server
3. Disables password authentication for security

**For service-to-service access (opencode → lehel.xyz):**
1. OpenCode role generates a dedicated SSH key (`id_servy`) for accessing lehel.xyz
2. Public key is added to lehel.xyz's authorized_keys with Docker network restrictions
3. OpenCode containers automatically get the private key mounted

### Initial Server Setup

**First time connecting to a new server:**

```bash
# code.lehel.xyz requires root access to bootstrap setup
cd ansible && ansible-playbook servyy.yml -i production -l codey.lehel.xyz -u root

# Then Ansible will:
# 1. Create cda user with sudo privileges
# 2. Set up cda user's SSH authorized_keys
# 3. Disable password authentication
# 4. Deploy opencode with cross-server SSH access to lehel.xyz
```

### SSH Access Methods

**Your workstation → lehel.xyz (primary):**
```bash
ssh lehel.xyz                  # Uses SSH key from ~/.ssh/id_rsa.pub
ssh cda@lehel.xyz
```

**Your workstation → code.lehel.xyz (opencode server):**
```bash
ssh code.lehel.xyz             # Uses SSH key from ~/.ssh/id_rsa.pub
ssh cda@code.lehel.xyz         # Initial deployment still uses root access
ssh root@code.lehel.xyz        # For emergency access (Ansible-configured)
```

**OpenCode service (code.lehel.xyz) → lehel.xyz:**
```bash
# Automatically configured by opencode role
# Private key: /home/cda/servyy-container/opencode/.ssh/id_servy
# Used by: OpenCode containers to sync/pull from lehel.xyz
# Restricted: Docker networks only (172.16.0.0/12, 127.0.0.1)
```

### SSH Key Requirements

Ensure you have a local SSH public key before deploying:

```bash
# Check if key exists
ls -la ~/.ssh/id_rsa.pub

# If missing, generate one
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
```

The Ansible setup uses this key for all servers.


## CRITICAL DEPLOYMENT RULES

**MANDATORY WORKFLOW - NO EXCEPTIONS:**

1. **NO Direct Server File Transfers**
   - ❌ **NEVER** use `scp`, `rsync`, or direct file transfers to servers
   - ❌ **NEVER** ssh into servers to manually edit files when git repo is active
   - ✅ **ALWAYS** use git workflow: create branch → commit → deploy via Ansible
   - This is a git-tracked repository - all changes MUST go through version control

2. **Test-First Deployment**
   - ✅ **ALWAYS** test on `servyy-test.lxd` first using `./servyy-test.sh`
   - ✅ **ALWAYS** verify services work correctly on test environment
   - ❌ **NEVER** deploy directly to production without testing

3. **Production Deployment Requires Explicit Approval**
   - ✅ **ALWAYS** ask user for explicit approval before deploying to production
   - ✅ **ALWAYS** identify which server(s) will be affected (check inventory first!)
   - ✅ **ALWAYS** show what will be deployed and ask "Should I deploy to {server}?"
   - ❌ **NEVER** assume production deployment is approved
   - ❌ **NEVER** deploy to production automatically
   - ❌ **NEVER** deploy to the wrong server (verify inventory: which server has this service?)

**Standard Git Workflow:**
```bash
# 1. Create feature branch
git checkout -b claude/feature-name

# 2. Make changes and commit
git add .
git commit -m "feat: description"

# 3. Test on test environment
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh

# 4. Verify test deployment works
ssh servyy-test.lxd "docker ps"

# 5. ASK USER FOR APPROVAL before production deployment
# Only after explicit user approval:
cd ansible && ./servyy.sh --limit servy.lehel.xyz
```


## Deployment Workflow

### Standard Deployment Process

```bash
# 1. Make changes to configuration files
# 2. Test syntax
cd ansible && ansible-playbook servyy.yml --syntax-check

# 3. Deploy to production
./servyy.sh --limit servy.lehel.xyz

# 4. Verify deployment
ssh lehel.xyz "docker ps | grep {service}"
ssh lehel.xyz "docker logs {service} --tail 20"
```

### Emergency Manual Updates (AVOID IF POSSIBLE)

**⚠️ WARNING:** Manual changes violate git workflow and should only be used in emergencies.
**ALWAYS** commit manual changes to git afterwards to keep repository in sync.

```bash
# Emergency example: Restart service only (NO file edits)
ssh lehel.xyz "docker restart monitor.grafana"

# If emergency file edit is absolutely required:
# 1. Make the change on server
# 2. IMMEDIATELY replicate change in git repo
# 3. Commit to git with explanation
# 4. Deploy via Ansible to verify git state matches server state
```

### Never `git pull` the deploy checkout on the server

`/home/cda/servyy-container` is the Ansible **remote dir**, not a workspace: a
repo sync runs `git reset --hard` there, and any manual `git pull` bypasses the
tasks that keep the stack startable.

The monitor stack no longer depends on the checkout's content for its secrets:
the contact points (the admin address) and — since 2026-11-20 — the datasources
(the `prometheus.lehel.xyz` basic-auth credential), plus the Loki push password
and scrape target, are rendered by Ansible into `monitor/rendered/`, an
**untracked** directory that `monitor/docker-compose.yml` bind-mounts over the
tracked paths. `monitor/promtail.yml` carries only the (non-secret) Loki tenant
inline. So a repo sync can no longer revert a config the containers read — that
was the 2026-10-30 trap, fixed on 2026-11-18 and extended on 2026-11-20.

What a hand-run `git pull` still breaks: it updates files the *deploy* has not
rendered/recreated yet (compose files, `grafana.env` consumers) without applying
them — deploy with `./servyy.sh --tags user.docker.repo,user.docker.monitor`
instead, or `--tags user.repo.clone` if you only need the checkout.

If a monitor file ever does hold raw `{{ ... }}` on the server (invalid YAML —
Grafana 13 exits 1 on a provisioning error and crash-loops; promtail fails to
parse its config at the next restart), the sanctioned repair is a redeploy:
`./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.monitor`
(add `--limit codey.lehel.xyz` for the Grafana/Loki half). That path also
re-asserts the resolved address and datasource credential, so the deploy fails
loudly rather than provisioning a broken monitor. Full write-up:
`history/2026-10-30_monitor-provisioning-render-trap.md`,
`history/2026-11-18_monitor-render-out-of-checkout.md` and
`history/2026-11-20_grafana-loki-to-codey.md`.

## Removing a Service Permanently

**Never remove services manually. Always use Ansible to decommission services.**

### Step 1: Remove Service from Server

Run the interactive removal playbook with confirmation prompt:

```bash
cd ansible
ansible-playbook plays/remove_service.yml -e "target_host=servy.lehel.xyz"

# Prompts for:
# 1. Service name (e.g., 'opencode')
# 2. Confirmation ("Remove {service} containers, volumes, and directory? (yes/no)")
#
# Removes: containers, volumes, and service directory
```

### Step 2: Disable Service in Inventory

Disable the service in version control to prevent re-deployment:

```bash
# Edit: ansible/production
# Change the service flag from true to false:
#   services_enabled:
#     {service}: false    # ← Was 'true'

# Example for removing 'opencode':
git diff ansible/production
# Should show: -          opencode: true
#            +          opencode: false

git add ansible/production
git commit -m "chore: disable {service} service

- Containers and volumes removed from [hostname]
- Service marked as disabled in inventory
"
```

### Step 3: Clean Up Git Repository

Remove the service directory from version control:

```bash
# Remove service directory (if exists in git)
git rm -r {service}/

# Or if directory isn't in git:
# Just remove from git index if tracked
git status | grep "deleted:" # Verify removal

# Remove EVERY registry entry (missing one causes stale Grafana alerts
# or silent re-deploys) — see the manage-service skill's Service Removal
# Checklist for the full list:
# - ansible/plays/user.yml: docker_service role invocation
# - ansible/plays/vars/secrets.yml: docker.services[] entry + secrets block
# - ansible/plays/vars/default.yml: docker_backend_services[] entry (probe-only
#   backend services; otherwise backend_container_not_running alerts forever for
#   a service nothing deploys)
# - ansible/plays/roles/user/tasks/docker_extras.yml: forall list entry
# - ansible/servyy.yml: testing.extra_hosts entry (if added)
# - ansible/testing: services_enabled entry (if present)
# - DNS records + check-server-status skill table

# Re-commit with service directory removal if applicable
git commit --amend -m "chore: remove {service} service

- Removed service directory from git
- Disabled in inventory (containers/volumes cleaned up on [hostname])
"

git push origin master
```

### Step 4: Deploy to Apply Inventory Changes

Deploy to confirm service is no longer deployed on next run:

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "system.probe"

# Verify in output:
# - Service role should be skipped (when condition: service not in enabled list)
# - No "Deploy {service}" task should run
# - Grafana: no system_container_running{name="{service}.*"} and the rule for its
#   tier Normal (container_not_running for app, backend_container_not_running for backend)
```

### Recovery (if needed)

If you need to re-enable a service:

```bash
# Edit: ansible/production
# Change:  {service}: false
# To:      {service}: true

# Then deploy:
cd ansible && ./servyy.sh --limit servy.lehel.xyz

# Service will be redeployed (if directory exists in git)
```


## git-crypt (CRITICAL)

**Encrypted patterns:** `*.yaml`, `*.env`, `*.conf`, `secrets.*`, `secret_*`, `git/htpasswd`

**Not encrypted (since 2026-10-29): `docker-compose.yml`** — the hosted Renovate app reads the
repo through the GitHub API, so ciphertext blobs made every `image:` tag invisible to it and no
compose image was ever bumped. Compose files are plaintext now, which means: **never put a
secret inline in one.** Secrets go in a `*.env` file rendered from `plays/vars/secrets.yml`
(see `photoprism/photoprism.env.j2`). Two CI/deploy guards enforce the rest: compose files must
stay plaintext (`.github/scripts/validate-git-crypt.sh`) and nothing may publish a port on all
interfaces except Traefik 80/443 (`ansible/plays/roles/user/files/check_published_ports.py`).
Safety audit: `history/2026-10-29_exposure-guards.md`.

**Rules:**
- Files appear as **plaintext when unlocked** - edit normally
- Auto-encrypted on commit (except compose files)
- Check status: `git-crypt status`


## Architecture

```
Internet → Porkbun DNS (*.lehel.xyz) → Hetzner Firewall → Traefik (443/80)
    → Docker "proxy" network → Services
    → Promtail → Loki (log aggregation)
```

**Tech Stack:** Docker Compose | Traefik | Ansible | git-crypt | Prometheus/Grafana/Loki | fail2ban


## Service Naming

```
Container: {directory}.{compose-service}
URL: {directory}.{inventory-hostname}

Example:
- Directory: monitor/
- Compose service: grafana
- Container: monitor.grafana
- URL: https://monitor.lehel.xyz
```

**Environments:**
- Production: `*.lehel.xyz` (lehel.xyz host)
- Test: `*.servyy-test.lxd` (LXD container), `*.runny-test.lxd` (runner rehearsal VM)

**⚠️ CRITICAL: DO NOT NAME SERVICES "app"**
- ❌ Never use `app` as a docker-compose service name or container name
- ❌ Reason: DNS conflicts when multiple services named "app" exist on same networks
- ✅ Use descriptive names: `finance-api`, `api`, `backend`, `webserver`, etc.
- ✅ Example: `leagues-finance.finance-api` instead of `leagues-finance.app`

This prevents DNS ambiguity where `getent hosts app` returns wrong service IP.

## Per-Server Service Deployment

**IMPORTANT:** Services are now deployed **per-server**, not uniformly across all servers.

Each server has its own set of enabled services defined in the ansible inventory. Before deploying or troubleshooting a service, **verify which server hosts that service**.

### How to Determine Which Server Has Which Service

**1. Check the Ansible Inventory**
```bash
grep -A 100 "services_enabled:" ansible/production

# Output will show which services are enabled per server:
# lehel.xyz:
#   services_enabled:
#     traefik: true
#     monitor: true
#     opencode: true
#     photoprism: true
#     ...
#
# code.lehel:
#   services_enabled:
#     opencode: true
#     ...
```

**2. Query Running Services on a Server**
```bash
ssh {server} "docker ps --format '{{.Names}}'"

# Example:
ssh code.lehel "docker ps"  # Lists services on code.lehel
ssh lehel.xyz "docker ps"   # Lists services on lehel.xyz
```

**3. Deployment by Server**
When deploying a service, **always specify the correct server**:

```bash
# Deploy opencode to code.lehel ONLY
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit codey.lehel.xyz

# Deploy all services to lehel.xyz
cd ansible && ./servyy.sh --limit servy.lehel.xyz

# Deploy all Docker services to all servers
cd ansible && ./servyy.sh --tags "user.docker" --limit all
```

### Common Per-Server Configurations

| Server | Role | Services |
|--------|------|----------|
| `servy.lehel.xyz` | Primary production | traefik, monitor, photoprism, git, ci (Forgejo), leaguesphere-*, etc. |
| `codey.lehel.xyz` | Secondary (opencode + claude-hub) | opencode, claude-hub, Forgejo runner (dind) |
| `runny-test.lxd` | Test (runner rehearsal, `test-runner` group) | Forgejo runner rehearsal (rootless) |
| `servyy-test.lxd` | Test environment | Mirrors production for validation |
| `runny.lehel.xyz` | CI runner (amd64) | Forgejo runner (rootless backend — no root-run containers) + node-exporter |

### Agent Responsibility: Know Your Server

When responding to requests like "deploy X" or "fix error in X":

1. **Identify the service**: What service is being referenced?
2. **Find the host**: Which server runs this service? (check inventory or `docker ps`)
3. **Connect to correct server**: `ssh {server}` before diagnosing or deploying
4. **Deploy to correct server**: Always use `--limit {server}` in ansible commands

**Example:**
- Request: "Deploy opencode"
- Action: Check inventory → opencode is on `codey.lehel.xyz` → Deploy with `--limit codey.lehel.xyz`
- Not: ~~Deploy to servy.lehel.xyz~~ (wrong server!)

## Key Services

| Service | Container Name | URL | Purpose |
|---------|---------------|-----|---------|
| traefik | traefik.traefik | traefik.lehel.xyz | Reverse proxy, SSL. Dashboard is behind HTTP basic auth (`traefik-auth` file-provider middleware, credentials in Vaultwarden — see `history/2026-10-22_traefik-dashboard-password-rotation.md`) |
| monitor | `monitor.grafana` + `monitor.loki` on `codey.lehel.xyz`; `monitor.prometheus`, `monitor.promtail`, `monitor.{cadvisor,node-exporter,pushgateway}` on `servy.lehel.xyz` (one compose project, two profiles — see `monitor/AGENTS.md`) | monitor.lehel.xyz | Observability stack; the two authenticated cross-host routes are `loki.lehel.xyz` (codey) and `prometheus.lehel.xyz` (servy) |
| photoprism | photoprism.photoprism | photoprism.lehel.xyz | Photo library |
| git | git.www | git.lehel.xyz | Git hosting (EOL nginx-git; Forgejo is its planned successor) |
| ci | ci.forgejo | ci.lehel.xyz | Forgejo Git + Actions (SQLite, private; runners on codey + runny). Git over HTTPS (token) and SSH `git@ci.lehel.xyz` on port 22 through servy's host sshd (passthrough as host user `git`, no published port). See `ci/AGENTS.md` "Git over SSH" |
| leaguesphere-demo | leaguesphere-demo.{www,demo-app,mysql} | demo.leaguesphere.app | LeagueSphere demo (auto-resets nightly) |
| claude-hub | claude-hub.hub | *(none — `traefik.enable=false`, SSH/CLI only)* | Headless Claude Code session dispatcher on `codey.lehel.xyz`; see [claude-hub/AGENTS.md](claude-hub/AGENTS.md). |

> **LeagueSphere prod/stage/demo/test environments, setup, logs, and the
> "investigate-on-prod / reproduce-with-prod-data-on-stage" workflows:** see
> [docs/AGENTS.md](docs/AGENTS.md) and
> [docs/leaguesphere-environments.md](docs/leaguesphere-environments.md).

**Logging Flow:**
- All Docker containers → stdout/stderr
- Promtail scrapes Docker logs + system logs (`/var/log/syslog`, `/var/log/auth.log`)
- Loki stores logs with 31-day retention
- Grafana provides log exploration + dashboards

## Backup & Monitoring

**Backups** (systemd timers → `/mnt/storagebox/backup/`):
- Home directory: 03:00 UTC daily
- Root filesystem: 04:00 UTC daily
- PhotoPrism DB: 02:00 UTC daily

**Monitoring Stack** (split across two hosts since 2026-11-20 — see `monitor/AGENTS.md`):
- **Prometheus:** Metrics collection (Traefik, cAdvisor, Node Exporter) — on servy
- **Grafana:** Dashboards (HTTP Errors, Security, Services & Infra) — on codey
- **Loki:** Log aggregation (31-day retention) — on codey
- **Promtail:** Log collection (Docker + system logs) — on servy, pushes to `loki.lehel.xyz`
- **monit:** System health monitoring (SSH, disk, memory)
- **fail2ban:** Intrusion prevention
  - Loki-based: SSH brute force, scanners, Traefik rate limiting, malicious bots
  - Script: `/usr/local/bin/blocklist/update-from-loki.sh` (runs every 5min)
  - Queries Loki through the authenticated `loki.lehel.xyz` route

## Troubleshooting

### Container Issues
```bash
# Check container status
ssh lehel.xyz "docker ps -a | grep {service}"

# View logs
ssh lehel.xyz "docker logs {container} --tail 50 --follow"

# Restart container
ssh lehel.xyz "cd servyy-container/{service} && docker-compose restart"

# Check .env file
ssh lehel.xyz "cat /home/cda/servyy-container/{service}/.env"
```

### Network Issues
```bash
# Inspect proxy network
ssh lehel.xyz "docker network inspect proxy"

# Check Traefik routing
ssh lehel.xyz "docker logs traefik.traefik --tail 50"
```


## Common Issues & Solutions

### Environment File Naming Issues

**Problem:** Ansible deployment fails with "env file not found"
- **Cause:** Hardcoded `docker_env_file` in role vars overrides env_suffix logic
- **Solution:** Remove hardcoded `docker_env_file` from role invocation, let defaults handle it
- **Reference:** `history/2026-05-31_staging_env_file_fix.md`

```bash
# ❌ Wrong - prevents env_suffix from being appended
- role: ls_app
  vars:
    docker_env_file: ".env"  # This overrides suffix logic!

# ✅ Correct - lets default logic work
- role: ls_app
  vars:
    # No docker_env_file override - suffix will be appended
```

### Orphaned Containers Blocking Redeployment

**Problem:** Docker-compose fails saying container already exists
- **Cause:** Renamed/removed compose services leave old containers running
- **Solution:** Manually remove orphaned containers before redeployment
- **Reference:** `feedback_orphaned_containers.md`

```bash
# Find orphaned containers
ssh lehel.xyz "docker ps -a | grep {old_service_name}"

# Remove them
ssh lehel.xyz "docker rm {container_id}"

# Then retry deployment
cd ansible && ./servyy-test.sh
```

### LeagueSphere Network DNS Resolution Failures

**Problem:** Frontend can't reach backend - "unknown host" errors
- **Cause:** Multi-network containers need backend service on same networks as frontend
- **Solution:** Ensure backend service is on the `proxy` network
- **Reference:** `leaguesphere_network_dns.md`

```yaml
# ✅ Correct - backend on proxy network
services:
  backend:
    networks:
      - proxy        # Frontend can reach it via this network
      - internal     # Can also have private networks
```

### Deployment Requires Git Push First

**Problem:** Server can't find changes - "Permission denied" or file not found
- **Cause:** Ansible deploys from git, but server hasn't pulled latest commits
- **Solution:** Push to origin first, ensure server's git pull succeeds
- **Reference:** `feedback_deployment_git_pull.md`

```bash
# 1. Commit changes locally
git commit -m "feat: description"

# 2. Push to origin FIRST
git push origin master

# 3. Server's Ansible will pull during deployment
# (servyy.sh runs: git pull origin master)
```

### Test Environment Not Initialized

**Problem:** `servyy-test.sh` fails with "container not found" or permission errors
- **Cause:** Test LXD container hasn't been created or is misconfigured
- **Solution:** Initialize test container first

```bash
# Initialize test environment
cd scripts && ./setup_test_container.sh

# Then deploy
cd ../ansible && ./servyy-test.sh
```

## Common Pitfalls

1. **Container label mismatch:** Always verify actual container name with `docker ps`, not the compose service name
2. **Loki query vs query_range:** Use `/api/v1/query_range` for log stream queries, NOT `/api/v1/query`
3. **git-crypt locked files:** Run `git-crypt status` if files appear binary
4. **Ansible changes not applied:** Check if templates are deployed to correct paths with `--check` mode
5. **Dashboard not updating:** Restart Grafana after provisioning changes — **on codey** since 2026-11-20: `ssh codey.lehel.xyz "docker restart monitor.grafana"`
6. **DNS service conflicts:** DO NOT use "app" as a service name - causes DNS ambiguity across networks. Use descriptive names like `finance-api`, `backend`, `webserver`, etc.

## Deployment Verification Checklist

Use this checklist after each deployment (test or production) to verify success:

### Pre-Deployment

- [ ] Changes committed to git
- [ ] Pushed to origin/master (if production)
- [ ] Tested on servyy-test.lxd (if production)
- [ ] All Ansible syntax checks passed: `ansible-playbook servyy.yml --syntax-check`
- [ ] User approved production deployment (if applicable)

### Ansible Execution

- [ ] Deployment completed without errors (exit code 0)
- [ ] PLAY RECAP shows: `failed=0` and `unreachable=0`
- [ ] Expected number of tasks ran (compare to previous deployments)
- [ ] No unexpected `FAILED` entries in output

### Docker Services

```bash
# Check all containers are running
ssh {host} "docker ps | wc -l"  # Compare to expected count

# Verify key services are healthy
ssh {host} "docker ps | grep traefik"
ssh {host} "docker ps | grep monitor"

# Check for restart loops (many restarts = unhealthy)
ssh {host} "docker ps --format '{{.Names}}: {{.Restarts}}' | grep -v ' 0$'"
```

### Network & Routing

```bash
# Verify proxy network exists
ssh {host} "docker network ls | grep proxy"

# Check Traefik is routing correctly
ssh {host} "curl -I https://{service}.{host} 2>/dev/null | head -1"
```

### Logs & Monitoring

```bash
# Check for errors in Traefik logs
ssh {host} "docker logs traefik.traefik --tail 20 | grep -i error"

# Check system logs for deployment issues
ssh {host} "journalctl -u docker --no-pager -n 20"

# Verify Loki is receiving logs (Loki + Grafana live on codey since 2026-11-20)
curl -s -u "promtail:<password>" -H "X-Scope-OrgID: servyy-logs-k8x9m2p4q7" \
  "https://loki.lehel.xyz/loki/api/v1/label/__name__/values" | jq length
```

### Environment-Specific Checks

**For LeagueSphere deployments:**
```bash
# Check both production and staging containers
ssh {host} "docker ps | grep leaguesphere"

# Verify database connectivity
ssh {host} "docker logs leaguesphere.app --tail 20 | grep -i error"
ssh {host} "docker logs leaguesphere_stage.mysql --tail 20 | grep -i error"
```

**For production (lehel.xyz):**
```bash
# Verify SSL certificates are valid
ssh lehel.xyz "curl -I https://traefik.lehel.xyz 2>&1 | grep SSL"

# Check fail2ban is active
ssh lehel.xyz "sudo fail2ban-client status | grep -c 'jail'"
```

### Rollback Decision

If any check fails:
- [ ] Do NOT proceed with production deployment
- [ ] Investigate root cause in test environment
- [ ] Fix in git, commit, and re-test
- [ ] Only deploy after successful test verification

## Adding a New Service

1. Create `{service}/docker-compose.yml`:
```yaml
services:
  api:  # ✅ Use descriptive name (NOT "app")
    container_name: ${COMPOSE_PROJECT_NAME}.api
    image: {image}
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
networks:
  proxy:
    external: true
```
⚠️ **NEVER use "app" as service name** - causes DNS conflicts with other services

2. Enable it per host in `ansible/production` (`services_enabled:`) and in
`ansible/testing` if servyy-test needs it.

3. Add a role invocation to `ansible/plays/user.yml` using the `docker_service` role:
```yaml
# Simple service (single .env from docker.env.j2)
- role: docker_service
  vars:
    service_dir: my-service
  when: "'my-service' in (services | default([]))"
  tags: [user.docker, user.docker.my-service]

# Service with extra env templates
- role: docker_service
  vars:
    service_dir: my-service
    env_templates:
      - src: docker.env.j2
        dest: .env
      - src: my-service/.env.j2
        dest: service.env
  when: "'my-service' in (services | default([]))"
  tags: [user.docker, user.docker.my-service]
```

4. Register the service in every list (missing one causes silent gaps or
stale alerts):
- `ansible/plays/vars/secrets.yml` → `docker.services[]` (`- {name, dir}`):
  drives the servy container-health probe, Pi-hole `dns.yml`,
  `host_ping.yml`, and testing `/etc/hosts`. Skip codey-only services
  here (e.g. `opencode` was removed 2026-10-10 — it runs on codey while
  the probe runs on servy); put test-only DNS in `ansible/servyy.yml`
  `testing.extra_hosts` instead.
- `ansible/plays/vars/default.yml` → `docker_backend_services[]` (`- {dir}`):
  services the container-health probe must watch that must NOT be in
  `docker.services` (backend-only, no Traefik router: `shared`). That list
  also creates Pi-hole DNS, `host_ping.yml` URLs and testing `/etc/hosts`,
  so a backend-only service there gets a name with no router behind it: the
  ping check gets a 404 and can never pass.
- `ansible/plays/roles/user/tasks/docker_extras.yml` → `forall_docker_services.sh` list.
- Secrets block in `ansible/plays/vars/secrets.yml` + env template under
  `ansible/plays/roles/docker_service/templates/<service>/` if needed.
- DNS via `dns-master` + Traefik `Host()` labels; update the
  `check-server-status` skill's enabled-services table.

5. Deploy: `cd ansible && ./servyy.sh --tags "user.docker" --limit servy.lehel.xyz`

5. Verify:
```bash
ssh lehel.xyz "docker ps | grep {service}"
ssh lehel.xyz "docker logs {service}.api --tail 20"
curl -I https://{service}.lehel.xyz
```

## Conventions

**Commits:** `<type>: <description>`
- Types: `feat`, `fix`, `chore`, `refactor`, `docs`
- Example: `fix: correct Traefik container label in Loki queries`
- Branch on prod must always be `master` after rollout; branches are only allowed during deployment.

**Branches:** `master` (production), `claude/*` (development)

**History logs:** Create `history/YYYY-MM-DD_description.md` for major changes


## Key Paths

| Location | Purpose |
|----------|---------|
| `/home/cda/servyy-container/{service}/` | Service directories on server |
| `/mnt/storagebox/backup/` | Backup storage |
| `/usr/local/bin/blocklist/update-from-loki.sh` | fail2ban Loki integration |
| `/var/log/fail2ban-loki.log` | fail2ban blocklist log |
| `ansible/plays/vars/secrets.yml` | Encrypted Ansible secrets (incl. `vaultwarden_api` API key) |
| `ansible/plays/vars/.restic_password_{home,root,ls_db}` | Restic password seed files (**source of truth**) |
| `ansible/plays/vars/.traefik_dashboard_password` | Traefik dashboard passphrase seed (**source of truth**, gitignored; hashed into `traefik/dashboard-auth.htpasswd`) |
| `ansible/plays/vars/.monitor_grafana_admin_password` | Grafana admin password seed (**source of truth**, gitignored; rendered into `monitor/grafana.env`) |
| `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` | Push restic passwords into Vaultwarden (handler-driven backup copy) |
| `ansible/plays/monitor_vaultwarden.yml` | Push the Grafana admin password into Vaultwarden (recovery copy, `--tags monitor.vaultwarden`) |
| `ansible/plays/roles/docker_service/templates/docker.env.j2` | Default service .env template |
| `ansible/plays/roles/docker_service/templates/{service}/` | Per-service env templates |
| `monitor/provisioning/dashboards/` | Grafana dashboard JSON files |
| `monitor/provisioning/datasources/` | Grafana datasource **Jinja source** (rendered to `monitor/rendered/datasources.yml`, which compose mounts) |
| `monitor/rendered/` | Untracked, Ansible-rendered monitor config (`contact-points.yml`, `datasources.yml`, `loki-password`, `loki-target.json`) |


## Quick Reference

```bash
# Deployment
cd ansible && ./servyy.sh --limit servy.lehel.xyz

# Verify services
ssh lehel.xyz "docker ps"

# Check logs
ssh lehel.xyz "docker logs traefik.traefik --tail 20"

# Restart Grafana (runs on codey since 2026-11-20; Prometheus stays on servy)
ssh codey.lehel.xyz "docker restart monitor.grafana"
ssh servy.lehel.xyz "docker restart monitor.prometheus"

# Test fail2ban
ssh lehel.xyz "sudo bash /usr/local/bin/blocklist/update-from-loki.sh"

# LeagueSphere demo management
ssh lehel.xyz "docker ps | grep leaguesphere-demo"              # Check demo containers
ssh lehel.xyz "docker logs leaguesphere-demo.demo-app --tail 20" # View demo logs
# Manual reset (Ofelia also runs this nightly at 00:00 UTC)
ssh lehel.xyz "docker exec leaguesphere-demo.demo-app /bin/bash -c 'rm -f /app/.demo_last_reset && /app/entrypoint.demo.sh'"

# View Loki logs
# Navigate to: https://monitor.lehel.xyz → Explore → Loki
# Query: {job="docker",container="traefik.traefik"} | json
```

## Backup & Recovery Rules

1. **Restic Restore Safeguards (MANDATORY)**
   - ❌ **NEVER** restore data while the target container is running
   - ❌ **NEVER** restore data into a non-empty directory (prevents corruption/overwrite)
   - ✅ **ALWAYS** verify target state (stopped container, empty/missing dir) before restore
   - ✅ **ALWAYS** test restore logic on `servyy-test.lxd` before applying to production

2. **Password Integrity**
   - ❌ **NEVER** overwrite Restic environment files (`/etc/restic/env.*`) if the password differs
   - ✅ **Manual intervention** is required if Restic passwords need to be changed/synchronized

3. **Repository Lockout Recovery**
   - **Manual Only:** Run `cd ansible && ./servyy.sh --limit <hostname> --tags restic.recreate`
     to wipe and re-init locked repos (there is no standalone recreate playbook)
   - **Verification:** The playbook automatically verifies lockouts and requires explicit confirmation

4. **Off-host Password Backup (Vaultwarden)**
   - The restic passwords are mirrored into Vaultwarden (`pass.lehel.xyz`) as a human-readable backup copy
   - **Source of truth stays the seed files** `ansible/plays/vars/.restic_password_*` — Vaultwarden is a *copy*, not the master
   - **Automatic, handler-driven:** the play resolves the Vaultwarden master password at the start of every run — read from `~/.ssh/vw.key` (mode 0600) when present, otherwise prompted (press enter to skip; `-e vw_master_password=…` always wins). The push fires only when `init.yml` actually writes/updates an `/etc/restic/env.*` file, and only on production (`lehel.xyz`). Idempotent — creates missing Login items only. API key from `secrets.yml` (`vaultwarden_api`).
   - To force a push when nothing changed, re-run with the env files dirty (or temporarily touch them) — there is no standalone playbook.
   - ⚠️ Do **not** make Vaultwarden the source restic reads from at deploy time — restic backs up Vaultwarden, so a bare-metal restore must not depend on it. Keep an offline copy of the master + restic passwords.
   - Reference: `history/2026-06-29_restic-vaultwarden-copy.md`

5. **Seed-Password Recovery Guard (prevents silent generation)**
   - The restic role runs `tasks/seed_guard.yml` FIRST (before any `restic_password_*`
     is dereferenced). If a seed file `ansible/plays/vars/.restic_password_*` is missing
     (fresh/re-cloned controller), it refuses to let Ansible silently generate a new
     password. Recovery precedence: **seed file → Vaultwarden (auto) → operator prompt → generate**.
   - Missing seed + blank Vaultwarden master password (or `bw` unreachable) → **hard-fail**.
     Provide the VW master password at the prompt to pull the password from Vaultwarden,
     or restore the seed files from your offline copy first.
   - A new password is generated ONLY when the operator leaves the prompt blank after
     Vaultwarden was actually probed and had no matching item — i.e. a never-initialized repo.
   - Guards init AND the destructive `restic.recreate` path (so recreate's wipe/re-init
     decision uses the real password, not a wrong-password artifact).
   - Reference: `history/2026-06-29_restic-seed-guard.md`

6. **Controller-local Seed Secrets (drift hazard)**
   - `vault_monitor_grafana_admin_password`, `vault_moodle_db_{,root_}password` and
     `vaultwarden_admin_token` come from `lookup('password', 'vars/.<name> …')`. Their seed
     files are gitignored, so they exist **only on the controller that first rendered them**.
   - Deploying from a controller that lacks a seed **generates a new random value** and
     renders it over the live config. That is the 2026-10-31 Grafana admin password drift:
     a deploy from the opencode server's checkout (no seed) rewrote `monitor/grafana.env`
     on servy while Grafana's DB kept the original password.
   - Only restic has a guard that refuses to generate (`roles/restic/tasks/seed_guard.yml`,
     rule 5). Grafana, Moodle and the Vaultwarden admin token have **no guard**: before
     deploying from a new controller, copy the seed files from the original controller
     (offline copy) or recover the value from Vaultwarden first.
   - Grafana applies `GF_SECURITY_ADMIN_PASSWORD` only when it first creates the admin user,
     so an env/DB mismatch does not change the working password — but recreating the
     `grafana_data` volume would adopt the drifted value. Check with
     `curl -u admin:<env pw> http://localhost:3000/api/user` (200 = env and DB agree).
     Since 2026-11-18 a monitor deploy **reconciles this itself**
     (`roles/monitor_grafana_auth`): it authenticates with the container's own env value and, only
     on a 401, re-asserts that value into `grafana.db` with `grafana cli admin reset-admin-password
     --password-from-stdin`, then fails the deploy unless the API answers 200. So a 401 on a
     verification recipe means "run `--tags user.docker.monitor`", not "the password is wrong" —
     and a password changed in the UI is reverted by the next monitor deploy, because the rendered
     env is the credential (this is deliberate; see
     [`history/2026-11-18_db-tier-r2b-alert-truth.md`](history/2026-11-18_db-tier-r2b-alert-truth.md)).
   - Recovery copy in Vaultwarden: `bw get password "grafana - admin (lehel.xyz)"`.
     Re-push after a rotation with
     `cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags monitor.vaultwarden`.
   - Reference: `history/2026-11-01_grafana-admin-password-drift.md`

> **Note:** there is no standalone `ansible-playbook restic_recreate.yml`; recreate runs
> via `--tags restic.recreate` through the restic role.


## Moved sections (for reference)

- Molecule testing workflow and scenario matrix: [ansible/AGENTS.md](ansible/AGENTS.md)
- Loki query recipes and fail2ban troubleshooting: [monitor/AGENTS.md](monitor/AGENTS.md)
- Service-to-Service SSH (OpenCode): [opencode/AGENTS.md](opencode/AGENTS.md)
- Cleanup and apt-upgrade timers: [scripts/AGENTS.md](scripts/AGENTS.md)
