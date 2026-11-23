# runny runs CI without root — the rootless runner backend

**Date:** 2026-11-23
**Branch:** `master` (Tasks 0–6 of `docs/plans/2026-11-23_runny-docker-trust.md`)

## Summary

On `runny.lehel.xyz` (the amd64 Forgejo Actions runner, an Oracle E2.1.Micro),
the Forgejo runner and every job now run **without root**. The runner is the
`rootless` backend of the `forgejo_runner` role: the `forgejo-runner` binary and
a rootless `dockerd` run as systemd **--user** services of the unprivileged
`runner` user, and the root-run `docker.service` / `docker.socket` /
`containerd.service` are **MASKED**. No dind, no compose project, no socket
mapping, no `--privileged` container anywhere in the chain. Jobs still build
images with `docker/setup-buildx-action` + `docker/build-push-action`.

## Problem (F5, F6)

A probe (`cda/energy.consumption` on `ci.lehel.xyz`) showed that whoever holds
the Docker daemon socket is root on the host: a job on runny could
`docker run --rm -v /:/host:ro alpine`, read `data/.runner` (the registration
secret) and every container, and escape the 900 MB job cap (F5). codey's
privileged dind model is root-on-the-host by construction (F6). The stop-gap
(Task 0, `container.docker_host: "-"`) revoked the job socket; this plan removed
root from the whole chain.

## Decision (§4)

Rootless Docker plus the forgejo-runner binary, both as systemd user services of
`runner`. Rejected: dind and rootless-dind sidecars (privileged in the chain),
a runner container on the rootless daemon (socket mapping + compose buy nothing
on a single-purpose host), jobs straight on the host (no Docker builds).

## Files

- `ansible/plays/roles/forgejo_runner/` — `rootless` backend:
  `defaults/main.yml` (user `runner`, subid `296608:65536`, binary URL, cache
  port, pasta net driver), `tasks/rootless.yml` (mask → gpasswd → user → subuid
  → AppArmor assert → apt → linger → binary → dirs → templates → start docker →
  register → start runner → remove legacy), `templates/rootless/`
  (docker.service.j2, forgejo-runner.service.j2, daemon.json.j2,
  docker-prune.{service,timer}.j2, cache-firewall.sh.j2), `handlers/main.yml`.
- `ansible/plays/roles/forgejo_bootstrap/` — `--scope` + `--keep-labels` on the
  runner registration (Task 6 scoping).
- `ansible/plays/roles/system/tasks/{main,firewall}.yml` — import `firewall.yml`
  when `with_docker` OR the runner node-exporter is on; gate the Docker
  edge-filter tasks on `with_docker` (Task 4).
- `ansible/production` — runny: `with_docker/with_containers: false`,
  `docker_cleanup.enabled: false`, `forgejo_runner_docker: rootless`,
  `forgejo_runner_cache_port: 41500`, drop `forgejo_runner_service_dir`;
  `forgejo_runner_scopes: {runny: cda}`.
- `monitor/provisioning/alerting/alert-rules.yml` — runner-offline description
  now the two user units on runny.
- `.claude/skills/check-server-status/SKILL.md`, `runny/AGENTS.md`, `CLAUDE.md`,
  `architecture/landscape.yaml` (runny 2 vCPU, 0 containers, rootless) —
  documentation updates.
- `scripts/setup_test_runner_vm.sh` — rehearsal VM on Ubuntu 26.04, 20 GiB disk,
  2 GiB RAM.

## Deploy output (runny, `./servyy.sh --limit runny.lehel.xyz`)

```
runny.lehel.xyz : ok=275 changed=38 unreachable=0 failed=0 skipped=485 rescued=0 ignored=3
```

The 3 `ignored` are the expected `systemctl --user` "user scope bus" rescues and
the storagebox-timer absence; none are real failures.

## Acceptance (§0) — all 14 pass on prod

`RUN=` = `sudo -u runner XDG_RUNTIME_DIR=/run/user/$(id -u runner)`.
Jobs ran on `cda/energy.consumption` @ `ci.lehel.xyz`, branch `forgejo-diag`,
`runs-on: amd64` (workflow `rootless-checks.yml`).

| # | check | result |
|---|---|---|
| 1 | `docker ps` as cda | `permission denied … /var/run/docker.sock` |
| 2 | `systemctl is-enabled docker.service docker.socket containerd.service` | `masked` ×3 |
| 3 | `$RUN systemctl --user is-active docker forgejo-runner` | `active` ×2 |
| 4 | job `docker info --format '{{json .SecurityOptions}}'` | `name=rootless`, `Driver=overlayfs` |
| 5 | job `--privileged head -c16 /dev/sda` | `Permission denied`, `rc=1` |
| 6 | job `-v /:/host:ro cat /host/etc/shadow` | `Permission denied`, `rc=1` |
| 7 | job `-v /:/host touch /host/root/x` | `Permission denied`, `rc=1` |
| 8 | job `-v /home/cda:/c ls /c` | `Permission denied` (`/home/cda` is 750) |
| 9 | job `--memory=900m` stress | OOM-killed (dmesg `Out of memory: Killed process … stress-ng-vm` in `docker-…scope`, `uid=1003`); `uptime` answers throughout |
| 10 | `sysctl kernel.apparmor_restrict_unprivileged_userns` | `= 1`; `grep -qx 'rootlesskit (unconfined)'` rc 0 |
| 11 | `build-push-action` | image built (`npm run build` 55 s, `docker-build=409 s` cold) |
| 12 | `setup-node` `cache: npm` ×2 | 2nd run `Cache restored successfully … node-cache-linux-x64-npm-…` |
| 13 | workstation `nc runny.lehel.xyz 41500` | v4 + v6 timeout (cache not internet-facing) |
| 14 | Prometheus target `runny.lehel.xyz:9100` | `up` |

`getent group docker` on runny lists no `cda`; `/home/cda/runny` removed; the
runner re-registered as `runner` (uid 1003), online `idle ['amd64']`.

## Benchmarks (Task 6, same `energy.consumption` commit)

| | GitHub | codey (dind) | runny (rootless, this change) |
|---|---|---|---|
| node job wall | 36 s | 103 s | 804 s → **failed** |
| `npm ci` cold / warm | ~12 s | 29 s / – | 178 s / 242 s |
| `lint` / `build` | 3 s / 10 s | 9 s / 31 s | 1 s / 29 s |
| `test` (vitest) | 10 s | 31 s | **failed** — `HookTimeoutError` 10000 ms, `TestTimeoutError` 5000 ms (mongodb-memory-server) |
| docker build cold / warm | 69–111 s | 86 s / 13 s | **409 s / 108 s** |

Idle `available` memory **580 MB** vs the 495 MB root-run baseline.

### Gate decisions

- **Docker gate: PASS.** Cold build 409 s ≤ ~750 s (2× the old 374 s). runny
  keeps amd64 docker jobs; no Kaniko/Buildah fallback needed.
- **Node gate: exclude the vitest suite on runny.** The mongodb-memory-server
  hook still misses its 10 s timeout on a 1-2 vCPU contended box (F1, unchanged).
  The project's `test` job must run on codey/GitHub, not runny; runny keeps
  `npm ci`/`lint`/`build`/docker-build.

## Scope (Task 6 step 4)

runny re-registered with `--scope cda` (and `--keep-labels`, which fixed the
Task 2 label-clobber finding — the `amd64` label survives re-registration).
Proved both ways on servyy-test first: a job in a throwaway second user's repo
(`probeout/outofscope`, `runs-on: amd64`) produced a `run_job` but **no**
`action_task` (no runner claimed it), while a `cda/energy.consumption` amd64 job
was picked up immediately. The throwaway repo and user were deleted.

## Rollback

Restore `ansible/production` runny (`with_docker/with_containers: true`,
`forgejo_runner_docker: host`, `forgejo_runner_service_dir: /home/cda/runny`,
drop `forgejo_runner_scopes`), unmask the three units, `./servyy.sh --limit
runny.lehel.xyz`. `docker_setup.yml` re-adds `cda` to `docker`; the runner
re-registers. Stop the user units by hand and remove the `runner` user in a
follow-up.

## Follow-ups

- **security_audit pip `umask`** — done (`umask: "0022"` on the pip task).
- **forgejo_bootstrap label clobber** — fixed here with `--keep-labels`.
- **vite 1 GiB OOM risk** — `npm run build` OOMs at 1 GiB without swap; runny
  has 4 GB swap and the build succeeds, but the E2.1.Micro is the floor. Re-check
  if a larger build lands on runny.
- **rootless has no cgroup swap controller** — delegated controllers are
  `cpu memory pids` (no `memory.swap`), so `memory.swap.max` is pinned to
  `memory.max`; job `--memory-swap` is effectively 0. Recorded, not blocking.
- **codey (§9)** — codey keeps privileged dind until a follow-up plan: it runs
  root-run services, so rootless.yml step 1 (mask + group removal) must become
  conditional; it needs `qemu-user-static`/`binfmt-support` on the host instead
  of `docker run --privileged tonistiigi/binfmt`; and a check that nothing
  sensitive on codey is world-readable (F7). Until then, scope codey's runner.
- **v17 deploy** — servyy-test already runs Forgejo 17.0.2 (prod is 15.0.12);
  re-check F4 (upload-artifact) and scoping after the v17 prod deploy.
