# 2026-08-06 — SearXNG: add engines + fix deploy/config bugs

## Problem
Brave search engine was rate-limiting the SearXNG instance (`search.lehel.xyz`).
The instance was restricted (`keep_only`) to `google`, `duckduckgo lite`, `brave`.

## Changes
1. **Added engines** `startpage`, `mojeek`, `qwant` to `keep_only` and gave each a
   `tokens:` block reusing `vault_searxng_brave_token` (all `vault_searxng_*_token`
   values are identical, so no `secrets.yml` change; existing preferences token
   keeps working). — `ansible/plays/templates/searxng/settings.yml.j2`
2. **Fixed deploy permission bug**: `Deploy searxng settings.yml` task now runs with
   `become: true` / `become_user: root`. `core-config/` on the server is root-owned
   (searxng runs as root and owns the dir + files), so the deploy user could not
   write `settings.yml`. — `ansible/plays/user.yml`
3. **Fixed dead engine**: renamed `duckduckgo lite` → `duckduckgo` in the template.
   Current SearXNG renamed the general-web DuckDuckGo engine; the old name no longer
   matches a default, so it failed to register (`engine field missing`) — it had been
   silently broken, effectively leaving only google + brave.

## Incident note
The first prod deploy stopped searxng (`Stop searxng before config update`,
`state: absent`) then failed on the permission bug (#2) before the restart role ran,
leaving `search.lehel.xyz` down. Fixed with #2 and redeployed. Downtime ~a few minutes.

## Deploy
```
cd ansible && ./servyy.sh --tags user.docker.searxng --limit lehel.xyz
```

## Verification
- `docker ps` → `searxng.core` + `searxng.valkey` Up
- `docker logs searxng.core` → no "can't register" / "engine field missing" errors
- `curl -s -o /dev/null -w '%{http_code}' https://search.lehel.xyz/` → 200
- `settings.yml` on server contains all 6 engines in `keep_only`

## Files changed
- `ansible/plays/templates/searxng/settings.yml.j2`
- `ansible/plays/user.yml`

4. **Removed redundant task**: deleted `Fix searxng core-config directory ownership`
   from `user.yml`. It chowned `core-config` to the deploy user so the (non-`become`)
   template could write — now unnecessary since the template writes as root. It was
   also a no-op that always reported `changed` without actually changing ownership.

## Commits (master)
- `feat(searxng): add startpage, mojeek, qwant engines`
- `fix(searxng): write settings.yml as root in deploy task`
- `fix(searxng): rename dead 'duckduckgo lite' engine to 'duckduckgo'`
- `chore(searxng): remove redundant core-config ownership fix task`
