# 2026-11-24 — AGENTS.md consolidation

**Problem:** `CLAUDE.md` (1,293 lines) and `AGENTS.md` (330 lines) duplicated operational
rules, and nine top-level components had no subdirectory guide. Agents had to know to read
both files, and the hierarchy convention (top level references subguides, each fact lives
once) was only partly followed.

**Decision:** hard-delete `CLAUDE.md`, keep `AGENTS.md` as the single entry point, and
distribute component-specific knowledge into per-directory guides. Only directories with
real complexity get a guide; single-compose service directories stay in the root Key
Services table. Historical records (`history/*.md`, old test reports) keep their original
wording.

## What was done

- Added eight guides: `ansible/`, `architecture/`, `claude-hub/`, `opencode/`, `hetzner/`,
  `scripts/`, `docs/`, `searxng/`. They cover playbooks/inventory/Molecule, the checked
  service landscape, the session dispatcher, cross-server SSH for OpenCode, the Hetzner
  firewall script, cleanup timers, LeagueSphere docs, and the SearXNG (no-valkey) setup.
- Moved Loki query recipes and fail2ban troubleshooting into `monitor/AGENTS.md` under
  "Querying logs and checking bans" — they were previously only in `CLAUDE.md`.
- Merged the repo-wide sections of `CLAUDE.md` into root `AGENTS.md`: quick commands, DNS,
  SSH, critical deployment rules, deployment workflow, service removal, git-crypt,
  service naming, per-server deployment, Key Services, backup/monitoring, troubleshooting,
  verification checklist, adding a service, conventions, key paths, quick reference and
  backup/recovery rules. Added a **Subdirectory guides** index linking all 17 guides.
  The `claude-hub` table row was shortened to a pointer; the stray final line about the
  production branch became a Conventions bullet.
- Repointed live references in `.claude/agents/`, `.claude/skills/`, Ansible role
  comments (including a comment inside encrypted `ansible/plays/vars/secrets.yml`),
  `ci/AGENTS.md`, `monitor/AGENTS.md` and `docs/leaguesphere-environments.md`.
  References to a *task workspace's* `CLAUDE.md` in `claude-hub/vendor/` and
  `claude-hub/skills/session-fleet/` were deliberately left alone — those are generated
  per-workspace files, not this repo's root file.
- Repointed the two `CLAUDE.md` mentions in the still-active
  `docs/plans/2026-11-23_runny-docker-trust.md` plan.
- Fixed a pre-existing broken link in `monitor/AGENTS.md` (the monitor reload role lives
  at `ansible/plays/roles/monitor_reload/`, not `ansible/plays/tasks/`).
- Deleted `CLAUDE.md`.

## Files changed

`AGENTS.md` (MODIFY), `CLAUDE.md` (DELETE), `ansible/AGENTS.md` (NEW),
`architecture/AGENTS.md` (NEW), `claude-hub/AGENTS.md` (NEW), `opencode/AGENTS.md` (NEW),
`hetzner/AGENTS.md` (NEW), `scripts/AGENTS.md` (NEW), `docs/AGENTS.md` (NEW),
`searxng/AGENTS.md` (NEW), `monitor/AGENTS.md` (MODIFY), plus the reference-repoint edits
listed above.

## Verification

```bash
# Only history/vendor/task-workspace references may remain
git grep -n 'CLAUDE\.md' -- ':!history/**' ':!claude-hub/**' ':!ansible/docs/testing/**'

# 18 AGENTS.md files (root + 17 subguides); 17 linked from the root index
for f in $(git ls-files '*AGENTS.md'); do test -f "$f" || exit 1; done
grep -c 'AGENTS.md](' AGENTS.md

# Secrets stayed encrypted
git-crypt status ansible/plays/vars/secrets.yml

# Relative links in changed Markdown resolve
python3 - <<'PY'
import re
from pathlib import Path
bad = []
for p in Path('.').rglob('AGENTS.md'):
    for link in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', p.read_text()):
        if link.startswith(('http://', 'https://')):
            continue
        if not (p.parent / link).exists():
            bad.append((str(p), link))
print('broken links:', bad)
PY
```

Result: no live `CLAUDE.md` references remain; root + 17 linked subguides; git-crypt reports
`secrets.yml` encrypted; no broken relative links in any `AGENTS.md`. No deployment —
documentation only.
