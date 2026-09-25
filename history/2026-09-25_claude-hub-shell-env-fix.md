# claude-hub: Bash Tool Broken by Missing $SHELL

**Date:** 2026-09-25
**Author:** Claude (via user dachrisch)
**Type:** Bug Fix
**Status:** 🚧 Pending test verification (not yet deployed to production)

## Summary

The `claude-hub` hub session's Bash tool was completely broken: every command,
including `echo ok`, failed with `No suitable shell found. Claude CLI requires a
Posix shell environment. Please ensure you have a valid shell installed and the
SHELL environment variable set.` Root cause: `node:22-alpine` never sets `$SHELL`,
and the container's env vars (rendered `.env`/`claude-hub.env` + Ansible/compose
defaults) don't set it either. The Claude Code CLI's Bash tool requires `$SHELL`
explicitly — it does not fall back to the `/etc/passwd` shell entry, even though
that entry (`root:x:0:0:root:/root:/bin/sh`) is correct and `/bin/sh` exists and
works fine when invoked directly.

Discovered from inside the hub session itself, while trying to dispatch a new
`devhub` session via `/repo-task-dispatch` — the dispatch never got to `launch-session.sh`
because the hub's own Bash tool couldn't run anything.

## Root Cause Investigation

Confirmed directly on `codey.lehel.xyz`:

```
$ docker exec claude-hub.hub env | grep SHELL
SHELL=
$ docker exec claude-hub.hub sh -c 'getent passwd root'
root:x:0:0:root:/root:/bin/sh
$ docker exec claude-hub.hub which sh
/bin/sh
```

So the shell is present and correctly registered for root, but genuinely absent
from the process environment `tmux`/`claude` inherit. `tmux new-session ... "claude
--continue --remote-control 'hub'"` in `startup.sh` (and the equivalent in
`launch-session.sh`) starts fine — the failure surfaces one layer in, inside the
Claude CLI's own Bash tool, which hard-requires `$SHELL` and refuses to run
anything without it.

No existing service in this repo sets `$SHELL` (checked `opencode/`, `claude-hub/`,
and the `docker_service` role's env templates) — this is a new gap, not a
regression from a prior working config.

## Fix

Set `SHELL=/bin/sh` as a static `environment:` entry on the `hub` service in
`claude-hub/docker-compose.yml` (not templated — it's a constant container-runtime
fact, not a per-deploy/per-secret value, so it doesn't belong in
`docker.env.j2`/`claude-hub/.env.j2`):

```yaml
services:
  hub:
    entrypoint: [ "/bin/sh", "/scripts/startup.sh" ]
    environment:
      - SHELL=/bin/sh
    env_file:
      - .env
      - claude-hub.env
```

## Deployment

1. Branch: `claude/claude-hub-fix-shell-env`
2. Test on `servyy-test.lxd` (`claude-hub: true` in `ansible/testing`) via
   `./servyy-test.sh --tags "user.docker.claude-hub"`
3. Verify `docker exec claude-hub.hub env | grep SHELL` shows `SHELL=/bin/sh` and
   a fresh `docker exec claude-hub.hub sh /scripts/launch-session.sh <repo> <title>`
   (or the hub's own Bash tool) works
4. Production deploy to `codey.lehel.xyz` pending explicit user approval

## Files Changed

- `claude-hub/docker-compose.yml` — added `SHELL=/bin/sh` to the `hub` service
