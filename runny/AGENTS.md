# runny/ — Forgejo Actions runner (deployed to codey and runny.lehel.xyz)

The runner that executes Forgejo Actions jobs. One service dir, deployed to
**both** runner hosts by the `forgejo_runner` role (`--tags user.docker.runny`):

| Host | Runner name | Backend | Labels | Capacity |
|---|---|---|---|---|
| codey (A1, arm64) | `codey` | `dind` (privileged docker:dind sidecar) | `ubuntu-latest`, `docker`, `arm64` | 2, QEMU amd64 |
| runny (E2.1.Micro, amd64) | `runny` | `host` (host docker socket) | `amd64` | 1, 4 GB swap |

The compose (`docker-compose.yml`) and the runner `config.yml` are **templated**
by the `forgejo_runner` role from host vars — there is no committed static
compose here because the Docker backend differs per host:

- `forgejo_runner_docker: dind` — a `docker:dind` sidecar on an internal
  network. **Used on codey** because mounting codey's host socket would expose
  the claude-hub and opencode credentials to CI jobs.
- `forgejo_runner_docker: host` — the host socket. **Used on runny** (saves
  ~100 MB; the box holds no secrets).
- `forgejo_runner_qemu: true` — one-shot `tonistiigi/binfmt --install amd64` so
  arm64 codey can build amd64 images (QEMU fallback).

Both `config.yml` and the `.runner` registration file live in `./data`
(bind-mounted to `/data`, the runner's working dir). `config.yml` carries
labels / capacity / `container.options` (the memory caps); `.runner` is written
once by `forgejo-runner create-runner-file --secret <forgejo_runner_secrets[<runner>]>`.

## Runners are never backed up

`servyy-container/runny` is in `restic.home.excludes`; the DinD volume is a
docker volume the home job never sees; runny.lehel.xyz has no restic at all. A
lost runner is recreated by a redeploy (it re-registers from
`forgejo_runner_secrets[<runner>]`).

## Monitoring

runny runs a `node-exporter` (the only monitoring piece on that 1 GB host),
scraped by servy's Prometheus. See the history entry and
`monitor/provisioning/dashboards/infrastructure/forgejo-ci.json` for the runner
liveness / host-metric dashboards.
