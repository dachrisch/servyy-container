# OpenCode Session Prune Automation (2026-09-04)

## Problem
The opencode.web container accumulated 349 sessions (5,057 messages, 21,534 parts) in 7 days,
growing the session DB (`/root/.local/share/opencode/opencode.db`) to 752 MB and slowing the
UI down.

## Solution
Automated nightly pruning via the existing Ofelia scheduler (`portainer.ofelia`), which
auto-discovers containers with `ofelia.*` labels — same pattern as the finance
`daily-import` job.

- **Prune script** (`opencode/scripts/prune-sessions.py`, python3 stdlib only):
  - Deletes sessions older than `OPENCODE_PRUNE_HOURS` (default 24) plus all dependent rows
    (part, message, session_message, session_input, session_context_epoch, todo,
    session_share, event, event_sequence)
  - Purges `tool-output/` files older than retention
  - `busy_timeout=60000` so it never fights the running web server
  - `VACUUM` only when rows were actually deleted; tolerates lock contention
  - One-line log summary → `docker logs portainer.ofelia`
- **Ofelia labels** on the `opencode` service in `opencode/docker-compose.yml`:
  - `ofelia.enabled=true`
  - `ofelia.job-exec.prune-sessions.schedule=0 4 * * *`
  - `ofelia.job-exec.prune-sessions.command=python3 /scripts/prune-sessions.py`
  - Rides the existing `./scripts:/scripts:ro` mount, no new volumes

Manual one-off prune was already run in production on 2026-09-04 (752 MB → 55 MB,
340 sessions removed, backup kept at `opencode.db.bak-prune-20260904` on the host).

## Files Changed
- `opencode/scripts/prune-sessions.py` - Prune script (new)
- `opencode/docker-compose.yml` - Ofelia job-exec labels
- `history/2026-09-04_opencode-session-prune-automation.md` - This document

## Verification
```bash
# Job registered?
ssh lehel.xyz "docker exec portainer.ofelia ofelia list | grep prune-sessions"

# Manual run
ssh lehel.xyz "docker exec portainer.ofelia ofelia run prune-sessions"

# Output
ssh lehel.xyz "docker logs portainer.ofelia 2>&1 | grep prune-sessions | tail"

# DB size after first run
ssh lehel.xyz "docker exec opencode.web du -sh /root/.local/share/opencode/opencode.db"
```

## Deployment
```bash
cd ansible && ./servyy-test.sh --tags "user.docker.opencode"
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit lehel.xyz
```

## Rollback
Remove the three `ofelia.*` labels from `opencode/docker-compose.yml` and redeploy; the
script is inert unless scheduled.
