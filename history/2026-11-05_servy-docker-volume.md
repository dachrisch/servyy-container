# ADR-005: Keep container data on a dedicated volume

**Date:** 2026-11-05
**Status:** Accepted
**Relates to:** ADR-001 (Infrastructure as Code), 2026-10-27 servy disk reclaim, 2025-12-09 extension drive

## Context

Nine days after the 2026-10-27 reclaim took servy from 65G to 46G used, the root
filesystem was back at **64G/75G (89%)**. Investigating produced three findings
that changed the fix:

1. **The image prune was not the problem.** `docker system df` advertised
   `Images 40 total, 40 ACTIVE, 27.92GB, reclaimable 27.92GB (100%)` — a
   containerd-image-store reporting artifact, not free space. The daily
   `docker system prune -a -f --volumes` had run 17h earlier and reclaimed 372MB;
   a manual `docker image prune -a` reclaimed 667MB of layers superseded since.
   `prune -a` already removes every image without a container, so the 28G that
   remained was *live*: 25G overlayfs snapshots + 4.5G content store.
2. **Docker is not where those layers live.** `dockerd` runs as
   `--containerd=/run/containerd/containerd.sock` against the system containerd
   2.2.2 with the containerd image store
   (`driver-type: io.containerd.snapshotter.v1`), so layers live under
   containerd's `root` (`/var/lib/containerd`), **not** under `daemon.json`'s
   `data-root` (5.7G of volumes). Moving `data-root` alone would have freed ~6G
   of 34G.
3. **`/mnt/10g_volume` had been a lie since April 2026.** The Hetzner volume was
   deleted, `has_10g_volume` was set to `false`, and `data-root` was left
   pointing at a plain directory on `/`.

The remaining growth was not Docker at all: `/home/cda/servyy-container/moodle/data`
had reached 8.0G (moodledata 5.9G + mariadb 2.2G) since the October reclaim.

Watchtower re-pulls every application image, so the image store churns ~1G/day
and a 75G root shared with `/home`, `/var/log` and the leaguesphere deploy jail
leaves no room for that churn.

### Alternatives investigated before deciding

**Storagebox (CIFS) as the image-store target — rejected on evidence.** Probed on
the live mount (`//u318127.your-storagebox.de/backup`, SMB 3.1.1, `soft,nounix`):

| Probe | Result | Required by |
|---|---|---|
| `mknod c 0 0` | `EOPNOTSUPP` (os error 95) | overlayfs whiteouts in the upperdir |
| `trusted.*` xattr | `EPERM` (`user.*` works) | overlayfs `trusted.overlay.*` metadata |
| hardlink | OK | — |
| 64MB direct write / read | 197 / 284 MB/s | irrelevant: container I/O is small random + metadata |

overlayfs cannot mount an upperdir without mknod and trusted xattrs, so the
snapshotter is structurally incompatible with that share — and with `soft` and
`nounix`, one SMB hiccup would I/O-error all 53 containers while ownership modes
are ignored. Archiving images there with `docker save` was also pointless: they
re-pull from Docker Hub in minutes.

## Decision

Attach a **50G Hetzner Cloud volume** (`servy-docker-data`, fsn1, ext4,
`discard,defaults`, `/dev/disk/by-id/scsi-0HC_Volume_107380154`) and move both
container data stores onto it:

- **containerd `root`** → `/mnt/servy-docker-data/containerd` (~30G of layers; the churn)
- **docker `data-root`** → `/mnt/servy-docker-data/docker` (5.7G of volumes + container metadata)

Sizing came from measurement, not the default: 28G containerd + 5.7G docker =
34G of data, leaving 15G of headroom for daily image churn at €2.86/month. The
planned 100G Moodle volume (`roles/user/tasks/moodle_volume.yml`) remains a
separate decision — `moodledata` stays on `/` for now.

The Ansible side makes the *destination* declarative and refuses to point
containerd at an empty directory, because a config pointing at a blank path
produces a daemon with no images and no containers — indistinguishable from data
loss. The copy itself is out-of-band work (stop → rsync → config → start) since
moving 34G is not idempotent configuration.

## Consequences

### Positive

- ✅ **root 64G → 29G used (86% → 40%)**, 44G free; the 1G/day image churn is gone from the root disk
- ✅ volume settles at 33G/49G (69%), monitored by an alert at 80%
- ✅ `data-root` finally names a path that exists
- ✅ `containerd`/`docker` restart ordering encoded in one handler (containerd-only restart strands dockerd on a dead socket with a stale `docker ps`)
- ✅ the change is reproducible and idempotent (`--check --tags system.extension_drive,system.containerd.store` → `changed=0`)

### Negative / Tradeoffs

- ⚠️ **`shared.db` (Postgres) PGDATA and `finance` uploads now sit on network block storage.** They were bind-mounted from `${DOCKER_DATA_ROOT}/finance/…`, so they followed the `data-root` move. Measured 123 MB/s writes and `pg_isready` clean at current load; if latency ever matters, move that bind back to `/` and keep only the image store on the volume.
- ⚠️ 50G is a hard ceiling; the alert fires at 80%, and growth past it needs an online `resize2fs` after a console resize.
- ⚠️ touching `containerd_config_path` now restarts containerd **and** docker (by design), i.e. a short platform-wide restart on that specific change.

### Implementation Details

**Host work (2026-11-05, ~6 minutes of downtime at 22:50):**

1. `mkfs.ext4 -L servy-docker-data`, mount at `/mnt/servy-docker-data`, fstab entry by device id; validated by `umount` + `mount -a`
2. Pre-seeded live: `rsync -aHAX --numeric-ids -x` of `/var/lib/containerd/` and `/mnt/10g_volume/docker/` (12 min) so the cutover was incremental
3. `systemctl stop docker.socket docker containerd` → final `rsync --delete -x` (2m15s + 42s) → `/etc/containerd/config.toml` (`version = 3`, `root = …`) + `daemon.json` `data-root` → `systemctl start containerd docker`
4. Recreated `shared.db` and `finance.firefly` so their `${DOCKER_DATA_ROOT}` binds moved; all 15 service `.env` files updated (and the Ansible template now renders the new path)
5. Verified, then deleted the 28G old store and the 5.7G old `data-root`

**Files modified:**

- `ansible/plays/vars/default.yml` (MODIFY) — `extension_drive` repointed (it still named the April-deleted volume); added `containerd_store_path`, `containerd_config_path`
- `ansible/production` (MODIFY) — `has_10g_volume` → `has_extension_drive`: `true` for servy, `false` for codey
- `ansible/plays/roles/system/tasks/containerd_store.yml` (NEW) — directory, populated-store guard, template, warn-instead-of-render when unmigrated
- `ansible/plays/roles/system/templates/containerd-config.toml.j2` (NEW) — `version = 3`, `root`, `state`
- `ansible/plays/roles/system/tasks/main.yml` (MODIFY) — include new task, renamed flag
- `ansible/plays/roles/system/handlers/main.yml` (MODIFY) — `restart containerd` handler looping `containerd`, `docker`
- `ansible/plays/roles/system/molecule/*/` (MODIFY) — flag rename across all five scenarios
- `monitor/provisioning/alerting/alert-rules.yml` (MODIFY) — `extension_disk_high_usage` un-paused and scoped to `mountpoint="/mnt/servy-docker-data"`
- `ansible/plays/roles/user/tasks/moodle_volume.yml` (MODIFY) — stale path comment
- `.claude/skills/check-server-status/SKILL.md` (MODIFY) — the volume added to the disk check
- `history/2026-11-05_servy-docker-volume.md` (NEW) — this ADR

**Commits:**

- `3ff74e9` feat: move servy's container data onto a dedicated 50G volume

**Testing & Verification:**

✅ contains the same 53 containers before and after (`53/53` running, `0` not-Up), 43 healthcheck-bearing containers healthy, 0 unhealthy  
✅ Traefik: `traefik.lehel.xyz` → 401, `monitor.lehel.xyz` → 302  
✅ public sites answering: bumbleflies 301, leaguesphere 301, m.leaguesphere 200, pass 200, git 200, finance 302, photoprism 307, demo.leaguesphere 301  
✅ `docker info`: `Docker Root Dir: /mnt/servy-docker-data/docker`, `driver-type: io.containerd.snapshotter.v1`; `containerd config dump` → `root = '/mnt/servy-docker-data/containerd'`  
✅ proof the volume is the live store: 896 files written there in 15 min vs 65 in the abandoned path; zero live mounts referenced the old paths before deletion  
✅ `shared.db`: `pg_isready` → accepting connections; mounts on the new path; finance UI 302  
✅ volume write test 123 MB/s; `findmnt` → `rw,relatime,discard`  
✅ zero `err`-priority journal entries for `containerd` and `docker` after the restart  
✅ `ansible-playbook plays/system.yml -i production --limit servy.lehel.xyz --check --tags system.extension_drive,system.containerd.store` → `changed=0` (idempotent)  
✅ `yamllint` clean, `servyy.yml --syntax-check` clean

**Key Learnings:**

1. **`docker system df` "reclaimable" is meaningless with the containerd image store.** It reported 100% of image size as reclaimable with every image active. Trust `prune -a` behaviour and the prune log; the number will send you hunting for garbage that does not exist.
2. **`rsync` without `-x` follows live container rootfs overlay mounts.** `/mnt/10g_volume/docker/rootfs/overlayfs/<id>` held 53 overlay mounts; copying them wrote 20G of merged container filesystems and filled the new 50G volume (`No space left on device`) on the first attempt. Always `-x` (or `--exclude rootfs`) when copying a docker/containerd data-root.
3. **Docker 29 + system containerd: `data-root` is not where the images are.** Check `docker info | grep driver-type` before planning a move.
4. **`${DOCKER_DATA_ROOT}` binds do not follow a `data-root` change** — bind sources are baked into a container at creation, so those containers must be recreated; a plain restart silently keeps reading the old path.
5. **The remote shell is zsh:** a failed glob (`rm -rf dir/*` → `no matches found`) silently skips the deletion while the rest of the script continues. Use `find … -mindepth 1 -delete` in ssh one-liners.

**Known Issues & Limitations:**

- A full reboot has not been exercised since the change. The volume is in `/etc/fstab` by device id and mounts at `local-fs.target`, which orders ahead of `containerd`/`docker`; the next unattended kernel reboot will prove it.
- `shared.db` PGDATA and `finance` uploads reside on the volume (see tradeoffs).
- The old 10G-volume era `extension_drive` variable names survive in historical documents (`history/2025-12-09_*`, plans) as records of what was true then.

## Related Decisions

- **ADR-001** — infrastructure as code: the volume definition, containerd config and alert ship through Ansible; only the one-off data copy ran by hand
- **ADR-004** — service undeployment via inventory control: the same inventory-flag pattern (`has_extension_drive`) is used to gate this per host
- 2026-10-27 servy disk reclaim — the change this one repairs; its daily-prune decision was correct and remains in place
- 2025-12-09 extension drive — introduced the volume this ADR replaces

## Alternatives Considered

### Alt A: Keep shrinking — prune harder, remove unused images

Pros: no new infrastructure, no cost, no downtime.
Cons: nothing left to prune — `prune -a` had already removed everything without a container, and the remaining 28G was in active use by 53 running containers.
**Rejected** — measured: 372MB/day of superseded layers, against 27.5G of reported (phantom) reclaimable space.

### Alt B: Offload the image store to the storagebox (CIFS)

Pros: 601G free, already mounted, zero additional cost.
Cons: `mknod` and `trusted.*` xattrs unavailable, so overlayfs cannot use an upperdir there at all; `soft,nounix` turns a network hiccup into I/O errors across every container.
**Rejected** — structurally impossible, not merely slow.

### Alt C: Move only `daemon.json`'s `data-root`

Pros: single config line, no containerd involvement.
Cons: with the containerd image store the layers are not under `data-root`; this would have moved 5.7G of a 34G problem and left the 28G churning on the root disk.
**Rejected** — `data-root` was 17% of the data.

### Alt D: Grow the root disk instead of adding a volume

Pros: one filesystem to watch; no path/ownership decisions.
Cons: mixes OS, `/home`, Moodle data and image churn on one filesystem again, so the next 1G/day spiral re-fills it; needs the root partition resized rather than an attached volume.
**Rejected** — the problem is churn co-located with user data, not total capacity.

### Alt E: 80G volume (the original suggestion) instead of 50G

Pros: ~38G headroom; Hetzner volumes scale IOPS with size.
Cons: measured data was 34G, and the planned 100G Moodle volume will take the growth curve; 50G costs €2.86/mo vs €4.58/mo and can be grown online later.
**Rejected in favour of 50G** — sized to measurement, not to the worst case.
