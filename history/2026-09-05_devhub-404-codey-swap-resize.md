# DevHub 404 / codey Disk Pressure — Swap Resize (2026-09-05)

## Problem

`https://h.code.lehel.xyz/` (DevHub) started returning `HTTP/2 404` with Traefik's own
"no matching router" body (`content-type: text/plain`, 19 bytes) — not an app-level 404.

## Root Cause

codey's root disk (`/dev/vda2`, 29GB) was at 98% capacity (611MB free). Watchtower
auto-updated `devhub.web` to v1.17.4 as designed; the fresh container's first request
triggered `SqliteError: disk I/O error, code: SQLITE_IOERR_SHMSIZE` while sizing the
SQLite WAL shared-memory file for `/data/devhub.db`, under that disk pressure. The
previous long-running container never needed to resize its already-mapped WAL file, so
it kept working right up until Watchtower swapped it out. Every request thereafter
(incl. the healthcheck) returned 500, Docker marked the container `unhealthy`, and
Traefik's Docker provider excludes unhealthy containers from routing — hence the 404.

Not a code regression (diffed devhub `v1.17.0`..`v1.17.4`: zero SQLite/db-related
changes). Not DNS, not Watchtower, not the network — all confirmed healthy.

Disk breakdown (of ~26.1GB used):
- `/10GB.swap` — 10.5GB (~40% of the disk)
- `opencode_opencode_root` docker volume — 7.4GB (out of scope here; see "Follow-up" below)
- `/var/cache/apt/archives` — 1.9GB, uncleaned since 2020
- docker images/containers (excl. above volume) — ~2.9GB

## Solution

1. **Made swap size a per-host config option.** `swap_space` in
   `ansible/plays/vars/default.yml` is now
   `"{{ swap_space_override | default('10G') }}"` instead of a hardcoded `10G`;
   `ansible/production` sets `swap_space_override: 5G` for `codey.lehel.xyz`.
2. **Added stale-swap-file cleanup** to `ansible/plays/roles/system/tasks/swap.yml`.
   The swap file's name encodes its size (`/{{ swap_space }}B.swap`), so changing the
   configured size points at a new file path — without cleanup, the old file would be
   left on disk and in `/etc/fstab`, growing swap usage instead of shrinking it. New
   tasks find any `.swap` entries in fstab that don't match the desired path and
   `swapoff` + fstab-remove + delete them before the existing create/format/enable
   tasks run.
3. Freed disk on codey: applied the resize (10G→5G swap), `apt-get clean`
   (1.9GB→44K), and triggered the existing weekly `docker-cleanup.service` on demand
   (reclaimed 237.9MB of stale images).
4. Restarted `devhub.web` once disk headroom existed — SQLite integrity check came back
   clean (`PRAGMA integrity_check` → `ok`); the `-shm` file recreated itself at the
   correct size on the next clean open.

## Testing

Molecule (Docker-based) and `servyy-test.sh` both already exclude `system.swap`
(`create_swap: false` / `--skip-tags system.swap`) — swap has never been exercised in
this project's automated test tiers, and LXD containers don't reliably support it.
Verified instead with a real (non-`--check`) apply against `servyy-test.lxd`, run
directly (bypassing the wrapper's tag skip):
- Created a 1G swapfile — passed.
- Resized 1G→2G — confirmed the new stale-cleanup logic fully removed the old file
  (disk, fstab, active swap) and only the new one remained active on the LXD host.
- Re-ran 2G unchanged — idempotent, no file recreation.
- Restored `servyy-test.lxd` to its exact original state afterward (no fstab, no swap
  file — it doesn't normally run swap at all).

Found and worked around (not fixed) a pre-existing, unrelated gap during testing: the
`add to fstab` task has no `create: yes`, so it fails outright if `/etc/fstab` doesn't
exist (true of `servyy-test.lxd`'s LXD container, not of real VM hosts). Left as-is at
the user's direction — real hosts (servy/codey) already have `/etc/fstab`.

## Deployment

```
cd ansible && ./servyy.sh --tags system.swap --limit codey.lehel.xyz < /dev/null
```
`PLAY RECAP: ok=29 changed=8 unreachable=0 failed=0`

## Verification

```
ssh codey.lehel.xyz "swapon --show"      # only /5GB.swap (file) + pre-existing /dev/vda3
ssh codey.lehel.xyz "df -h /"            # 97% (611MB free) -> 67% (9.0GB free)
docker inspect --format='{{.State.Health.Status}}' devhub.web   # healthy
curl -I https://h.code.lehel.xyz/        # HTTP/2 200
```
Traefik access log confirmed `RouterName: devhub@docker`, `DownstreamStatus: 200`.

## Files Changed

- `ansible/plays/vars/default.yml`
- `ansible/plays/roles/system/tasks/swap.yml`
- `ansible/production`

## Known Issues / Follow-up

- `ansible/plays/roles/system/tasks/swap.yml`'s `add to fstab` task still lacks
  `create: yes` (see Testing above) — latent, doesn't affect servy/codey today, but
  will block swap-role testing on any future fstab-less host again.
- **Not yet implemented**: a cleanup design was proposed for the opencode docker
  volume (7.4GB, still growing) — session snapshot packs (extend the existing
  `prune-sessions.py` Ofelia job), `opencode.log` rotation (new `logrotate` template,
  matching the existing `logrotate-docker-cleanup.j2` pattern), and periodic
  `npm cache clean --force`. The `dev/*` repo clones (3.78GB) were found to be the
  live, idempotently-resynced working set for every `gh-dash`-tagged repo (via
  `opencode/scripts/provision-dev.sh`), not stale cruft — deleting them wouldn't
  reclaim space (they'd just re-clone on next boot), so no action was proposed there
  beyond optional periodic `git gc`. Awaiting go-ahead to implement.
