# servy disk reclaim + job-search retirement

**Date:** 2026-10-27
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz`
**Relates to:** ADR-001 (infrastructure as code), the 2026-09-27 bumbleflies repository/archive retirement

## Context

`servy.lehel.xyz` sat at **65G used / 7.7G free of 75G (90%)** on its root
filesystem, with a 10G swap file, 32G of container images and a weekly image
prune. Prometheus `traefik_router_requests_total` was used to separate
*services worth keeping* from *disk* worth keeping; the biggest wins turned out
to be housekeeping, not service removal.

Measurements before the change:

| Where | Size |
|---|---|
| `/var/lib/containerd` (images) | 32G — 27G overlayfs snapshots, 5.1G content store |
| swap files `/10GB.swap` + `/2GB.swap` | 12.6G for **2.9G of actual swap use** |
| `/mnt/10g_volume/docker/volumes` | 5.6G (prometheus 2.25G, loki 1.26G, grafana 0.53G orphaned) |
| `/home/cda` | 3.4G (photoprism MySQL 0.78G, git repos 0.55G, trivy cache 1.4G) |
| `/root` | 3.1G (trivy cache 2.9G) |
| `/var/jail` (leaguesphere) | 1.9G — prod 0.68G, staging 0.48G, demo 0.24G |
| `/var/log` | 1.4G (journal 0.53G, process accounting 0.48G) |

## Decision

Two changes, split by ownership — anything Ansible renders is Ansible's job,
one-off caches are handled on the host.

### Tier 0 — reclaim disk without removing a service

1. **Swap resize, 10G → 6G** (`swap_space_override`). The host was carrying
   three fstab entries (`/2GB.swap`, `/8GB.swap`, `/10GB.swap`) from an earlier
   2G→10G resize; `/8GB.swap` did not even exist. The role's existing
   `system.swap.stale.cleanup` block was correct but had never run against this
   host (`/etc/fstab` mtime was 2026-06-23 — the system role had not been
   deployed since the fix landed).
2. **Docker cleanup weekly → daily.** Watchtower re-pulls every app image and
   churns ~1.3G/day of superseded layers.
3. **journald `SystemMaxUse` 500M → 200M.**
4. On the host: duplicate trivy DBs, orphan `monitor_grafana_data` volume,
   process-accounting retention 30d → 7d.

### Tier 2 — retire `job-search`

Ranked candidate by traffic (93 frontend requests/week over 7d) against
footprint (~1.3G: 3 images + mongo/redis volumes + a crawler running 24/7).
Removed everywhere, per the service-removal checklist.

## Consequences

### Positive

- ✅ **65G → 46G used, 7.7G → 27G free (90% → 63%)** — 19G reclaimed
- ✅ swap consolidated to one 6.3G file (still ~2x observed peak use)
- ✅ image steady state no longer grows for a week between prunes
- ✅ one fewer service to watch, patch and back up

### Negative / Tradeoffs

- ⚠️ `/etc/logrotate.d/acct` (a distro file, not in git) now rotates 7 instead
  of 30 days of process accounting — a package update could revert it
- ⚠️ `job-search` is gone; its history is recoverable only from git history and
  the mongo dump on the storagebox
- ⚠️ a 6G swap file gives less headroom than 10G if a new service is memory-heavy

### Implementation Details

**Files modified:**

- `ansible/plays/roles/system/tasks/swap.yml` — reordered + hardened (see learnings)
- `ansible/plays/vars/default.yml` — `docker_cleanup.schedule: '*-*-* 02:00'`, `journald.system_max_use: 200M`
- `ansible/production` — `swap_space_override: 6G`, `job-search: false`
- `ansible/plays/user.yml` — job-search role invocation + mongo auth/FCV migration tasks removed
- `ansible/plays/roles/user/tasks/docker_extras.yml`, `ansible/testing`, `ansible/plays/vars/secrets.yml` — job-search entries removed
- `job-search/docker-compose.yml` — deleted
- `ansible/plays/roles/docker_service/molecule/default/converge.yml` — comment marking the retained templates as fixtures
- `.claude/skills/check-server-status/SKILL.md`, `.claude/skills/servyy-branch-deploy/SKILL.md`, `traefik/dynamic.yaml` — references updated

**Commits:** `8b74d8d` (main change), `53487e3` (swap safety guards).

**Deploy:** `./servyy.sh --limit servy.lehel.xyz --tags "system.swap,system.docker.cleanup,system.journald"`
after a `--check --diff` run. Teardown of the service itself was on the host
(`docker compose down -v`, image removal, directory removal) because
`services_enabled: false` stops the role from running entirely — it does not
stop the containers.

**Data:** `job_search.users` (1 doc), `jobs` (52), `searchsessions` (2) —
dumped to `/mnt/storagebox/backup/retired-services/job-search-2026-10-27.archive.gz`
(12K, outside the restic repo directory).

**Reclaimed, by source:**

| Source | Freed |
|---|---|
| daily prune run (42 → 41 images, 34G → 25G) | ~9G |
| swap files 12.6G → 6.3G | 6.3G |
| trivy caches (duplicate DB + stale java-db) | 2.9G |
| job-search images + volumes | 1.3G |
| journald cap + pacct retention + orphan grafana volume | 1.2G |

### Verification

- ✅ `swapon --show` → single `/6GB.swap`, 1.3G used; fstab has one swap line
- ✅ `systemctl list-timers` → `docker-cleanup.timer` daily
- ✅ 50/50 containers `Up`, nothing restarting or unhealthy
- ✅ leaguesphere 301, photoprism 307, dontforget 200, search 200, bumbleflies 200
- ✅ `jobs.lehel.xyz` → 404 branded error page (expected for a removed host)
- ✅ no `job-search` container, volume or image left; no `job-search` probe series in Pushgateway
- ✅ `yamllint` clean on changed files, `ansible-lint` passes, `--syntax-check` passes

### Key Learnings

1. **`docker system df` lies under the containerd image store.** After the
   Oct 25 prune it reported *"Images 42 active, 25.97GB, reclaimable 25.97GB
   (100%)"* — 100% of in-use images cannot be reclaimable — and that prune
   returned only 2.0G. Never plan a reclaim from that number; measure
   `/var/lib/containerd` instead.
2. **Order matters when resizing swap.** `swapoff` must fault every live page
   back into RAM. The role removed the old file *before* creating the new one;
   on a host holding 2.9G in swap that is how you OOM mid-resize. Now the new
   swap is created and enabled first, and a still-active stale file aborts the
   play instead of being unlinked (unlinking an active swap file leaves the
   space allocated but invisible to `df`).
3. **`swapon -a` is wrong here** — it would switch on the stale fstab entries
   just so they can be switched off again. Explicit `swapon <file>` instead.
4. **A `--check` run could not dry-run a first-time swap resize**: `dd` is
   skipped, so the mode-0600 `file` task aborted with "absent, cannot
   continue".
5. **Ansible-rendered config that never ran is still wrong config.** The
   stale-swap cleanup logic existed and was correct; the host simply had not
   been deployed since it landed.
6. **Retirement candidates are ranked by traffic, but the traffic data has
   noise** — `catchall-websecure` (424k) dwarfs any real service, so scanner
   and prefetch noise has to be read around.

### Known Issues / Open Findings

- **`monitor.grafana` is defined in `monitor/docker-compose.yml` but no
  container exists**, and no Grafana router shows traffic in 30 days of
  Prometheus data. The 512M `monitor_grafana_data` volume was dropped as part
  of this work; dashboards/datasources/alerting are all file-provisioned under
  `monitor/provisioning/`, so a redeploy recreates them. **Whether Grafana was
  removed deliberately was never established** — worth confirming, because
  without it there are no dashboards and the provisioned alert rules do not
  evaluate.
- `/mnt/10g_volume` (5.6G, holding the docker volume store) sits on the same
  physical disk as `/` and is counted in the 63% — there is no separate volume
  on this host despite the name.
- leaguesphere staging (0.48G + ~640MB RSS) and demo (0.24G) remain the largest
  remaining "dev environment on production hardware" pair; the NEXT candidate if
  more space is needed.

## Alternatives Considered

### Alt A: `docker image prune -a` only, keep the weekly schedule
Pros: no new code
Cons: the prune returns ~2G, not the reported 23.77G, and the host re-fills within a week. **Rejected** — the churn, not the prune, was the problem.

### Alt B: keep 10G swap, only delete the stale 2G file
Pros: zero risk during resize
Cons: returns 2.1G of the 6.3G available and leaves a 10G file for 2.9G of use. **Rejected** — with the new file activated first the resize is safe.

### Alt C: retire leaguesphere staging/demo instead of housekeeping
Pros: 2G and 8 containers, real simplification
Cons: the same 2G is available from swap consolidation with no service impact. **Deferred** — still the best next candidate.

### Alt D: delete the `docker_service` job-search env templates with the service
Pros: no leftover references
Cons: they are the role's multi-env-template molecule fixture; deleting them breaks
`docker_service`'s only 3-env-file test case. **Rejected** — kept, with an inline note.

## Related Decisions

- 2026-09-27 bumbleflies repository/archive retirement — same traffic-driven method, same checklist
- ADR-004: service undeployment via inventory control — the checklist this followed
