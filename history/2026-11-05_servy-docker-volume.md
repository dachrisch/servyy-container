# servy: docker/containerd data moved to a dedicated 50G volume

**Date:** 2026-11-05
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz`
**Relates to:** 2026-10-27 servy disk reclaim (the 46G → 61G regression), 2025-12-09 extension drive (the volume that was deleted in April 2026)

## Context

Nine days after the 2026-10-27 reclaim took servy from 65G to 46G used, the root
filesystem was back at **64G/75G (89%)**. Two separate things were going on, and
only one of them was Docker:

| Finding | Evidence |
|---|---|
| `docker system df` claimed **27.5G reclaimable** | `Images 40 total, 40 ACTIVE, 27.92GB, reclaimable 27.92GB (100%)` — impossible with every image in use. Under the containerd image store the daemon reports 100% of image size as reclaimable regardless of use |
| The daily prune was working | `docker system prune -a -f --volumes` ran 2026-11-05 02:02, deleted 9 images, reclaimed 372MB; a manual `docker image prune -a` reclaimed 667MB of layers superseded since then. `prune -a` already removes every image with no container, so anything left is *live* |
| ~30G of those live images sat on the **root** disk | `/var/lib/containerd` 28G (25G overlayfs snapshots + 4.5G content), churning ~1G/day from watchtower re-pulls |
| The **rest** of the growth was Moodle | `/home/cda/servyy-container/moodle/data` 8.0G (moodledata 5.9G + mariadb 2.2G), created after the Oct 27 reclaim |
| `/mnt/10g_volume` was a **plain directory on `/`** | The Hetzner volume was removed in April 2026; docker's `data-root` still pointed at the path |

Storagebox was evaluated as an offload target and rejected on evidence, not
opinion: on that CIFS mount `mknod c 0 0` returns `EOPNOTSUPP` and `trusted.*`
xattrs return `EPERM` (only `user.*` work). overlayfs needs both for its upperdir
whiteouts and metadata, so the containerd snapshotter cannot live there at all —
and with `soft,nounix` a single SMB hiccup would fail every container at once.

## Decision

Attach a **50G Hetzner Cloud volume** (`servy-docker-data`, fsn1, ext4,
`discard,defaults`, `/dev/disk/by-id/scsi-0HC_Volume_107380154`) and move both
stores onto it:

- **containerd's `root`** → `/mnt/servy-docker-data/containerd` (~30G of layers, the churn)
- **docker's `data-root`** → `/mnt/servy-docker-data/docker` (5.7G of volumes + container metadata)

Sizing: 28G containerd + 5.7G docker = 34G of data, 15G headroom for the daily
image churn. The planned 100G Moodle volume (`moodle_volume.yml`) stays a
separate, later change — `moodledata` did not move here.

### Why the containerd config, not just `daemon.json`

`dockerd` runs as `--containerd=/run/containerd/containerd.sock` against the
system containerd (2.2.2), with the containerd image store
(`driver-type: io.containerd.snapshotter.v1`). Image layers therefore live in
containerd's `root`, **not** in docker's `data-root` — moving `data-root` alone
would have relocated 5.7G and left the 28G behind.

## Consequences

### Positive

- ✅ **root 64G → 29G used (86% → 40%)**, 44G free — the churn now happens on the volume
- ✅ volume settles at 33G/49G (69%), with a Prometheus alert at 80%
- ✅ `data-root` finally points at a path that exists (it had been naming a deleted volume since April)
- ✅ rollback kept available: the old store stayed on `/` until verified, then deleted

### Negative / Tradeoffs

- ⚠️ **`shared.db` (Postgres) PGDATA and `finance` uploads now live on the volume** — they were bind-mounted from `${DOCKER_DATA_ROOT}/finance/…`. Hetzner volumes are network block storage, so this adds I/O latency to that database. Acceptable for its size/load; if it becomes a problem, move `PGDATA` back to `/` and keep only the image store on the volume.
- ⚠️ a full `containerd`/`docker` restart is now part of any change to `containerd_config_path` (the handler restarts both, deliberately)
- ⚠️ 50G is a hard ceiling checked only at 80% — an image-set blow-up (new multi-GB service) needs a resize (`resize2fs` grows online)

## Implementation Details

**Host work (2026-11-05, ~6 minutes of downtime at 22:50):**

1. `mkfs.ext4 -L servy-docker-data`, mount at `/mnt/servy-docker-data`, fstab entry
   by device id with `discard,defaults` (mount remount-tested)
2. Pre-seed while live: `rsync -aHAX --numeric-ids -x /var/lib/containerd/` and
   `… /mnt/10g_volume/docker/` onto the volume (12 min), so the cutover was
   incremental
3. `systemctl stop docker.socket docker containerd` → final `rsync --delete -x`
   (2m15s + 42s) → write `/etc/containerd/config.toml` + repoint `daemon.json`
   → `systemctl start containerd docker`
4. Recreated `shared.db` and `finance.firefly` so their bind mounts moved off
   `${DOCKER_DATA_ROOT}=/mnt/10g_volume/docker`; all 15 service `.env` files
   updated to `/mnt/servy-docker-data/docker`
5. Verified: 53/53 containers up, 43 with healthchecks healthy, Traefik 401/302,
   bumbleflies/leaguesphere/moodle/pass/finance/git/photoprism all answering,
   zero journal errors in containerd/docker, then deleted the 28G old store and
   the 5.7G old data-root

**Files modified:**

- `ansible/plays/vars/default.yml` — `extension_drive` repointed (it still named the volume deleted in April); added `containerd_store_path` / `containerd_config_path`
- `ansible/production` — `has_10g_volume` → `has_extension_drive: true` (servy), `false` (codey)
- `ansible/plays/roles/system/tasks/containerd_store.yml` (new), `templates/containerd-config.toml.j2` (new) — renders `root` only when the destination store is already populated (a config pointing at an empty dir is indistinguishable from data loss)
- `ansible/plays/roles/system/tasks/main.yml` — include the new task, renamed flag
- `ansible/plays/roles/system/handlers/main.yml` — `restart containerd` handler that also restarts docker (a containerd-only restart leaves dockerd on a dead socket with a stale `docker ps`)
- `ansible/plays/roles/system/molecule/*/` — flag rename in all five scenarios
- `monitor/provisioning/alerting/alert-rules.yml` — `extension_disk_high_usage` un-paused, scoped to `mountpoint="/mnt/servy-docker-data"` (the old `mountpoint!="/"` filter also matched `/boot/efi` and the CIFS backup target)
- `ansible/plays/roles/user/tasks/moodle_volume.yml` — stale path comment
- `.claude/skills/check-server-status/SKILL.md` — volume added to the disk check

## Learnings

1. **`docker system df` "reclaimable" is meaningless with the containerd image store** — it reports 100% of image size even when every image is active. Trust `docker image prune -a` (it removes everything with no container) plus the prune log, not the number.
2. **`rsync` without `-x` follows the live container rootfs overlay mounts.** `/mnt/10g_volume/docker/rootfs/overlayfs/<id>` holds 53 overlay mounts; copying them wrote 20G of merged-container filesystems and filled the new volume (`No space left on device`). Use `-x` (or `--exclude rootfs`) for any docker/containerd data-root copy.
3. **Docker 29 + system containerd: `data-root` is not where the images are.** Check `docker info | grep driver-type` before planning a move; with the containerd snapshotter the layers are in containerd's `root`.
4. **`${DOCKER_DATA_ROOT}` binds don't follow a `data-root` change** — bind sources are baked into the container at create time, so those containers must be recreated (they keep reading the old path after a plain restart).
5. Remote shell is zsh: a failed glob (`rm -rf dir/*` → `no matches found`) silently skips the deletion. Prefer `find … -mindepth 1 -delete` over globs in ssh one-liners.
