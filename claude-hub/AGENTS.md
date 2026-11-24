# claude-hub/ — headless Claude Code session dispatcher

Runs on `codey.lehel.xyz` as `claude-hub.hub`. No public URL — `traefik.enable=false`,
SSH/CLI only. Deployed by the `docker_service` role.

## What it does

The hub session is still a foreground, `tmux`-wrapped process:

```bash
docker exec -it claude-hub.hub tmux attach -t hub
```

A task session it dispatches is a native `claude --bg --remote-control` job in its own
git-worktree workspace (`spinup-repo.sh` → vendored `spinup-session.mjs`), with the
lifecycle managed by a vendored `session-reaper.mjs`:

- park / revive / close-on-request
- hourly via codey's Ofelia scheduler
- weekly force-cleanup backstop for long-parked sessions

The hub shares its `/root/dev` checkouts with `opencode` through the
`codey_dev_checkouts` named volume. **opencode must deploy first** so the `external: true`
volume reference resolves — see `history/2026-09-22_claude-hub-service.md`.

## Files

- `docker-compose.yml` — the service definition; managed by Ansible, not hand-edited.
- `scripts/` — `spinup-repo.sh` and the other entry points.
- `skills/` — session-facing skills.
- `vendor/` — third-party code; [`vendor/VENDORED.md`](vendor/VENDORED.md) is the
  provenance record. Changes there must keep that file in sync.

## Reference

- `history/2026-09-26_claude-hub-worktree-dispatch-rework.md` — the dispatch design.
- [Root AGENTS.md](../AGENTS.md) — deployment rules, verification commands and Key Services table.
