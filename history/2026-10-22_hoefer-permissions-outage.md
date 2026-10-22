# höfer-architekten.de — 404 outage: 0660 site files → unhealthy nginx → no Traefik routers

**Date:** 2026-10-22
**Domain:** `höfer-architekten.de` (`xn--hfer-architekten-mwb.de`)
**Related service:** `achim-hoefer` (static site, nginx:stable on `servy.lehel.xyz`)
**Related:** `history/2026-10-22_hofer-architekten-transfer.md`

## Summary

The site went down again ~2h after the registrar-transfer work fixed it. UptimeRobot
reported `404`. This was **not** a second, independent fault: it is one chain that
starts with the deploy checkout's umask and ends with Traefik withdrawing the
service's routers.

```
deploy runs under umask 007
  → git restores tracked files as 0660 (dirs 0770)
  → nginx worker (uid 101, not cda, not group docker) cannot read ./serve → 403
  → compose healthcheck (`curl -I --fail http://localhost`) fails
  → container reports unhealthy
  → Traefik removes the container's routers while it is unhealthy
  → every request matches catchall-websecure@file → branded 404
  → UptimeRobot HTTP monitor: Down
```

## Root cause

`ansible/plays/roles/user/tasks/includes/repository.yml` does `git reset --hard`
and the `git` module with `force: true`, then `find … -exec chown cda:docker` —
**ownership only, modes untouched**. Git creates restorable files as `0666 & ~umask`,
and the deploy session's umask is `007`, so every rewritten file lands as `0660`
(directories `0770`): readable by `cda` and group `docker` only.

`achim-hoefer/serve` is bind-mounted into `nginx:stable`, whose worker runs as uid
101. uid 101 is neither the owner (`cda` = 1000) nor in group `docker`, so nginx
answers **403** for every request.

### Traefik withdraws routers for unhealthy containers (verified)

Two throwaway containers on the `proxy` network, same image, same label shape,
differing only in healthcheck:

| container | docker health | `curl -H Host:…` |
|---|---|---|
| `probe-bad` | unhealthy | `404` (catch-all) |
| `probe-good` | healthy | `200` |

That is why *all three* routers (`achim-hoefer`, `_prod`, `_local_qualified`)
disappeared at once and why the domain — not just one path — answered 404. Access
logs confirm `RouterName: catchall-websecure@file` for the host; nginx's own access
log shows no external requests at all, only failing healthchecks.

### Why the earlier fix did not hold

`history/2026-10-22_hofer-architekten-transfer.md` applied `chmod -R a+rX serve/`
by hand and recorded "two independent causes" (routers not bound to `websecure`
plus the 403. That reading was wrong: it was this one chain. `--force-recreate`
only appeared to fix it because it ran next to the `chmod`, and the recreate
generated the docker event that made Traefik re-read the now-healthy container.

The manual `chmod` was then silently reverted by the next deploy
(`git reset --hard` rewrote the files at 13:08), which is why the site failed again.

## Timeline (2026-10-22, CEST)

| time | event |
|---|---|
| 11:20:22 | UptimeRobot incident 1 resolved (after manual `chmod`) |
| 13:06–13:11 | deploy: `git reset --hard` + `git` module `force: true` in `/home/cda/servyy-container` |
| 13:08 | `achim-hoefer/{docker-compose.yml, update.sh, serve/*}` rewritten as `660`/`770` |
| 13:13:27 | UptimeRobot incident 2 starts: `404 Not Found` |
| 13:22 | diagnosed: container unhealthy, 29+ failing healthchecks, no routers in Traefik |
| 13:5x | `chmod -R a+rX serve/` → healthy → routers returned on their own → `200` |

## Fix

Immediate (applied): `chmod -R a+rX /home/cda/servyy-container/achim-hoefer/serve`.

Durable (this change):

- `docker_service` role gains `world_readable_paths` (default `[]`) and
  `tasks/permissions.yml`, which `chmod`s those paths with `mode: a+rX` — dirs
  `0775`, files `0664` — after the env files are rendered and before
  `docker compose up`.
- `plays/user.yml`: the `achim-hoefer` service declares `world_readable_paths: [serve]`.
- `repository.yml`: comment documenting that the checkout intentionally produces
  `0660`/`0770` (git-crypt secrets rely on group-only read) and that content a
  non-root container user must read has to be declared in `world_readable_paths`.
- Molecule (`docker_service/default`): converge creates a `serve/` dir `0770` with a
  `0660` file for a new `static-svc`, verify asserts `0775`/`0664`. Written but not
  executed locally (no docker socket in the dev container) — the task itself was
  exercised against a scratch dir: `770→775`, `660→664`, missing paths skipped,
  second run `changed=0`.

Deliberately **not** changed: the deploy umask. `0660` is wanted for the
git-crypt'd secret files; fixing this by globally running the checkout under
`022` would have been the wider fix and is the trap to avoid.

## Verification

```
https://höfer-architekten.de/              200  25984B  <title>Höfer Architekten - Website</title>
https://www.höfer-architekten.de/          200  25984B
https://höfer-architekten.de/impressum.html 200   5404B  <title>Impressum …
container achim-hoefer.www                 Up (healthy), FailingStreak 0
traefik routers                            websecure-achim-hoefer_prod@docker present again
```

## Impact Assessment

- No content, compose or Traefik configuration was modified for the immediate fix —
  permissions only.
- The 404 (not 403/500) was Traefik's catch-all: the site was *fully* unreachable,
  including its TLS-terminating router, for 2h.
- Any service whose container process runs as a non-root uid and reads
  bind-mounted repo content is exposed to the same failure after every deploy.

## Rollback Procedure

Revert the `docker_service` changes: drop `world_readable_paths` from the
`achim-hoefer` service block (the role then skips `permissions.yml` entirely).
The `0660` modes and the outage then return on the next deploy — this fix is the
rollback target of the previous manual `chmod` practice, not the other way round.

## Next Steps

- [ ] Run the `docker_service/default` molecule scenario where a docker socket is
      available (CI) to confirm the new assertions.
- [ ] Audit other services for bind-mounted content read by non-root container
      users (`grep` for `volumes:` referencing repo files, then check the image's
      runtime uid).
- [ ] Make the site's monitoring content-aware: a well-formed `404` from Traefik's
      error page satisfied a pure reachability check for two days in the transfer
      incident; assert on the `<title>` or a fingerprint instead.
- [ ] Consider a Traefik-side alert: `traefik_config_reloads_total` is fine while a
      whole service silently drops out of the router table — alert on
      "router count decreased" instead.
