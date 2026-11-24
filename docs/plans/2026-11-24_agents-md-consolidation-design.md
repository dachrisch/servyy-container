# AGENTS.md consolidation — design

> Temporary design record. Deleted when the work is closed (see [history/AGENTS.md](../../history/AGENTS.md)).

**Goal:** retire `CLAUDE.md` without losing operational knowledge, and close the AGENTS.md coverage gaps.

**Approved decisions:**
- Distribute content across the hierarchy; do not dump 1,300 lines into the root file.
- Add guides only for complex components: `ansible/`, `architecture/`, `claude-hub/`, `opencode/`, `hetzner/`, `scripts/`, `docs/`, `searxng/`. Single-compose directories stay covered by the root service table.
- Hard-delete `CLAUDE.md`; repoint every in-repo reference.

## Architecture

Root `AGENTS.md` stays the single entry point: its existing build/test/style material remains, and the repo-wide operational sections from `CLAUDE.md` are appended (quick commands, critical deployment rules, deployment workflow, DNS, SSH, service naming, per-server deployment, key services, service removal, git-crypt, backup/recovery, troubleshooting, verification checklist, adding a service, conventions, key paths, quick reference). A new **Subdirectory guides** index links all 17 guides.

## Content mapping

| CLAUDE.md section | Destination |
|---|---|
| Molecule Testing, Ansible Structure | `ansible/AGENTS.md` |
| Architecture | `architecture/AGENTS.md` (overview stays in root) |
| claude-hub row of Key Services | `claude-hub/AGENTS.md` (short row + link in root) |
| Service-to-Service SSH (OpenCode Access) | `opencode/AGENTS.md` |
| Loki Query Issues, fail2ban Issues, Loki query/label recipes in Deployment Workflow | `monitor/AGENTS.md` |
| Cleanup Automation | `scripts/AGENTS.md` |
| LeagueSphere environments note | `docs/AGENTS.md` (link from root) |
| Everything else | root `AGENTS.md` |

Each fact lives in one place. Where root already covers a topic (Molecule tests, emergency procedures, code style), the subdir guide holds the detail and root holds a short pointer.

## Verification

1. No `CLAUDE.md` references remain outside the history entry.
2. Every relative markdown link in changed files resolves.
3. Every former `CLAUDE.md` heading maps to exactly one destination.
4. `git status` contains only intended changes; no new secrets.
5. Spot-check root and `ansible/AGENTS.md` readability.
