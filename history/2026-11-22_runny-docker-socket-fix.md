# runny can run Docker builds (job containers get the host socket)

**Date:** 2026-11-22
**Branch:** `master`

> ## Superseded 2026-11-23
>
> This change is reverted in intent by `docs/plans/2026-11-23_runny-docker-trust.md` (the
> "CI runners without root" plan). The grant below — handing the host daemon socket to job
> containers — is exactly the "F5: whoever holds the daemon socket has the host" finding: a
> job on runny could `docker run --rm -v /:/host:ro alpine`, read `data/.runner` (the
> registration secret) and every container, and escape the 900 MB job cap, i.e. root on
> runny. Task 0 of that plan makes `container.docker_host: "-"` on the host backend (jobs get
> no daemon socket); the ultimate shape is rootless Docker on the host. Keep the benchmark
> table and the two findings below for the record.

## Problem

A probe migration (`https://github.com/dachrisch/energy.consumption` → a private
`cda/energy.consumption` on `ci.lehel.xyz`) showed that **no job on runny can
use Docker**:

```
$ docker version            # inside a job container on runny
failed to connect to the docker API at unix:///var/run/docker.sock;
$ ls -l /var/run/docker.sock
ls: cannot access '/var/run/docker.sock': No such file or directory
```

The runner container has had the host socket all along
(`docker-compose.yml.j2`, host backend). What was missing is the **second**
mount: the one the runner hands to *job* containers.

`config.yml.j2` rendered `container.docker_host: ""` for the host backend,
on the assumption that an empty value means "find `/var/run/docker.sock` and
mount it". That is not how runner 13.2.1 behaves: the act default only applies
when the flag is unset, and the daemon always sets it from `config.yml`. Empty
therefore means **no mount at all**. codey was unaffected only because the dind
branch passed an explicit value (`unix:///var/run/dind/docker.sock`).

Consequence: `docker`/`docker build` in a runny job failed immediately, and
`docker-runny` in the benchmark died in its first step.

## What was done

| File | Change |
|---|---|
| `ansible/plays/roles/forgejo_runner/templates/config.yml.j2` | `container.docker_host` now renders `{{ forgejo_runner_docker_host }}` for **both** backends (`unix:///var/run/docker.sock` on the host backend, `unix:///var/run/dind/docker.sock` on dind), with a comment recording that empty ≠ auto-detect. |
| `ansible/plays/roles/forgejo_runner/tasks/main.yml` | The render task registers its result and a new task restarts `runny.runner` when the config changed. `docker compose up -d` does **not** recreate a container for a bind-mount content change, so a config-only deploy used to leave the old config running. |
| `ansible/plays/roles/forgejo_runner/molecule/default/verify.yml` | Two assertions: the rendered dind and host `config.yml` each carry the expected non-empty `docker_host`. |

## Deployment

```bash
cd ansible
ansible-playbook plays/user.yml --tags user.docker.runny --limit runny.lehel.xyz -i production
```

Rendered the fix (`--check --diff` first), then the runner was restarted once by
hand because the config had already been written by an earlier run that aborted
before the restart task. Re-running the play is idempotent (`changed=0`).

## Verification

Inside a job container on runny, after the fix:

```
srw-rw---- 1 root 106 0 /var/run/docker.sock
1237 1225 0:29 /docker.sock /run/docker.sock rw,nosuid,nodev - tmpfs
Client: 29.9.3-1     Server: 29.1.3
```

Docker build of the probe repo's `Dockerfile` (same commit, same runner):

| | cold (0 B build cache) | warm (1.43 GB build cache) |
|---|---|---|
| runny (E2.1.Micro, host socket) | **374 s**, 699 MB image | **109 s**, 699 MB image |
| codey (A1.Flex arm64, dind) | 86 s | 13 s |
| GitHub `ubuntu-latest` (gha cache) | 69–111 s | – |

**Trust boundary unchanged in kind, larger in fact:** any job on runny can now
drive runny's Docker daemon, i.e. root on that box. That is the documented
model (`runny/AGENTS.md`: the host holds no repo checkout, no secrets, no
restic), so the blast radius is runny itself — but it is worth knowing that a
workflow that only *reads* the repo can now also start containers there.

## Not done (found by the same probe, left for a separate change)

- `fail2ban loki-blocklist` bans runny (`92.5.160.254`) whenever it streams job
  logs: `traefik-aggressive-crawler attempts=202…206` against a 200/2 min
  threshold. The runner's 2 s task polling plus log streaming is by itself "an
  aggressive crawler". Bans hit IPv4 only (`DOCKER-USER` REJECT), so the runner
  dials `49.13.6.173:443` and gets `connection refused` while IPv6 works; log
  and status uploads are lost mid-job. Fix: exclude
  `/api/actions/runner.v1/*` in `update-blocklist-from-loki.sh.j2` (crawler and
  request-rate queries).
- The Actions **cache** endpoint is unreachable from runny's job containers: the
  runner advertises its compose-network IP (`172.19.0.2:41495`), jobs live on a
  `WORKFLOW-*` bridge. `setup-node` with `cache: npm` hangs in `SYN_SENT` for
  minutes. codey (dind) is unaffected.
- `architecture/landscape.yaml` lists runny as **1 vCPU**; `nproc` says 2
  (E2.1.Micro = 1 OCPU × 2 threads).

## Benchmarks for the record (same commit, `f5812d3`)

Node job (`npm ci` → `lint` → `build` → `vitest`), from the same probe:

| | GitHub | codey | runny |
|---|---|---|---|
| `npm ci` cold | ~12 s (cached) | 29 s | 160 s |
| `build` | 3 s | 9 s | 48 s |
| `test` | 10 s | 31 s | 402 s → **failed** (`mongodb-memory-server` misses its 10 s hook timeout) |
| job wall | 36 s | 103 s | 966 s |

Molecule could not be run on the workstation that made this change (no Docker
there); the role's two new assertions run in CI.
