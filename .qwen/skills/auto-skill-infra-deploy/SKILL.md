---
name: infra-deploy
description: How to deploy Ansible changes to the servyy infrastructure with narrow tags and verify on server
source: auto-skill
extracted_at: '2026-07-14T12:30:00.000Z'
---

# Skills Index
- [infra-deploy](auto-skill-infra-deploy/SKILL.md) — Deploy Ansible changes with narrow tags and verify
- [leaguesphere-maintenance-toggle](auto-skill-leaguesphere-maintenance-toggle/SKILL.md) — Toggle LS maintenance mode via Django admin

# Infrastructure Deployment Procedure

## Context
This is the `infrastructure-container` repo managing `servyy` / `lehel.xyz` production servers via Ansible.

## Deploy with narrow tags

```bash
# 1. Verify the commit is on master and pushed
git log -1 --oneline

# 2. Deploy only the changed role/tasks using narrow tags
cd ansible && ./servyy.sh --limit lehel.xyz --tags <tag.name>

# Common tags:
#   system.restic.maintenance  — restic forget/check scripts + timers
#   ls.app.stage               — staging deployment
#   ls.db.sync                 — prod → stage DB clone
#   ls.db.migrate              — external → local prod DB seed
#   ls.stage.restore           — restore stage from physical backup
#   restic.restore             — file-level restic restore
```

## Verify on server

```bash
# Check deployed files
ssh lehel.xyz "cat /path/to/deployed/file"

# Check systemd services
ssh lehel.xyz "systemctl status <service>"

# Check Docker containers
ssh lehel.xyz "docker ps | grep <service>"
```

## Key scripts
- `ansible/servyy.sh` — `ansible-playbook servyy.yml -i production "$@"`
- `ansible/servyy-test.sh` — runs against `servyy-test.lxd`
- `scripts/setup_test_container.sh` — prepares test LXD container

## Rule: Test first, then production
Always run on test container before production unless the change is trivial (e.g. a single template update already validated).

## Lessons learned

### mariadb-backup copy-back breaks cross-environment restores
Direct `mariadb-backup --copy-back` into a different environment's MySQL container will break authentication because the backup includes the source's `mysql` system database (root password, users). Use the temp-container → mysqldump → import pattern instead. See skill: `mariadb-cross-env-restore`.

### rm -rf glob misses hidden files in MySQL data dirs
`rm -rf /path/to/mysql-data/*` does not remove dotfiles (e.g. `.ibd`, `.frm` metadata). Use `rm -rf /path/to/mysql-data && mkdir -p /path/to/mysql-data` to fully wipe.
