---
name: servyy-branch-deploy
description: Use when the user wants to build and run a branch (or any ref) of a containerized service directly on servyy-test.lxd without going through CI image builds — e.g. "deploy this branch on servyy-test", "spin up a preview of feature-x on the test host". Covers both replacing the running instance and running an isolated preview instance behind Traefik.
---

# Deploy a branch on servyy-test (no CI image build)

## Overview

Most services in this world are deployed from images that CI only builds on
tag pushes (or, for some, never — the image is built directly on the host).
When you need to run an arbitrary branch / feature ref on `servyy-test.lxd`,
you build the image **on servyy-test itself** (Docker is *not* available on the
local laptop — hard rule) and then (re)deploy it via the existing
`servyy-container` infra repo compose + Traefik, bypassing CI entirely.

Two modes:

- **replace** (default): build the branch image with the *exact tag the
  service's compose references* (e.g. `dachrisch/dontforget:latest`) and
  re-run the deploy, recreating the running container. Data volumes persist.
- **preview**: run a *separate, isolated* stack with its own Traefik host
  (e.g. `dontforget-feat.servyy-test.lxd`) so the running instance is
  untouched. Good for "test this branch without disturbing prod/test".

## Prerequisites / mental model

- `servyy-test.lxd` is an LXD container reachable over SSH (`ssh servyy-test.lxd`).
  Confirm it's up: `lxc list servyy-test --format json | jq -r '.[0].state.status'`.
- Infra repo on the laptop: `~/dev/infrastructure/container` (the
  `servyy-container` checkout). It is synced to `/home/cda/servyy-container`
  on the host by Ansible. Each service has a compose at
  `/home/cda/servyy-container/<service>/docker-compose.yml` plus rendered
  `.env` and (usually) a secrets env like `web.env`.
- Service "image tag" = the `image:` value in the service's compose on the
  host (read it first). For dontforget it is `dachrisch/dontforget:latest`.
- Secrets (api keys, smtp) live in the Ansible-rendered env file (git-crypt
  encrypted in the repo). For **replace** you reuse the already-rendered env
  on host — no re-render needed. For **preview** you copy it and adjust
  `PUBLIC_BASE_URL`.

## Step 1 — Get a clean source tree onto servyy-test

Docker context must exclude `.git`, `node_modules`, `dist`, etc. Two options:

**A. `git archive` (preferred — no push, no node_modules):**
```bash
git -C /path/to/apprepo archive <branch-or-ref> | \
  ssh servyy-test.lxd "rm -rf /tmp/<svc>-build && mkdir -p /tmp/<svc>-build && tar -x -C /tmp/<svc>-build"
```
Verify: `ssh servyy-test.lxd "test -f /tmp/<svc>-build/Dockerfile && echo OK"`.

**B. `git clone --branch`** (use when the ref is remote-only and not on disk):
```bash
ssh servyy-test.lxd "git clone --branch <branch> <repo-url> /tmp/<svc>-build"
```

## Step 2 — Build the image on servyy-test

```bash
ssh servyy-test.lxd "cd /tmp/<svc>-build && docker build -t <image-tag> ."
```
- `<image-tag>` MUST equal the compose's `image:` for **replace** mode.
- Capture the built image ID for the post-deploy check:
  `ssh servyy-test.lxd "docker inspect --format='{{.Id}}' <image-tag>"`.

## Step 3a — Replace mode (recreate the running instance)

The Ansible `docker_service` role does exactly: render envs → `docker compose up`.
Since the envs are already rendered on host and identical (same secrets), you
can invoke the same `docker compose up` directly — no need for the full
playbook run (which also re-syncs the infra repo and requires git-crypt).

```bash
ssh servyy-test.lxd "cd /home/cda/servyy-container/<service> && docker compose up -d"
```
- Compose reads `.env` from that dir for `${COMPOSE_PROJECT_NAME}` /
  `${SERVICE_NAME}` / `${SERVICE_HOST}` / `${TRAEFIK_*}` interpolation.
- Because the local image with the matching tag exists, compose uses it
  directly and does **not** pull from the registry (verify in step 5).
- Only the `web` (app) container is recreated; the `mongo`/db sidecar and its
  volume persist.

If you specifically want the canonical Ansible path (re-renders envs from the
infra repo's current checkout), run from `~/dev/infrastructure/container`:
```bash
cd ~/dev/infrastructure/container && ./ansible/servyy-test.sh --tags user.docker.<service>
```
Caveat: the `testing` inventory has no `services_enabled`, so the
`user.docker.<service>` task's `when: "'<service>' in services"` may skip —
prefer the direct `docker compose up` above unless you've confirmed the
inventory enables the service.

## Step 3b — Preview mode (isolated instance)

1. Slugify the branch: `SLUG=$(echo <branch> | tr '/' '-' | cut -c1-30)`.
2. On servyy-test, create a preview dir derived from the production one:
   ```bash
   ssh servyy-test.lxd "mkdir -p /home/cda/servyy-container/<service>-preview"
   ssh servyy-test.lxd "cp /home/cda/servyy-container/<service>/docker-compose.yml /home/cda/servyy-container/<service>-preview/"
   ```
3. Write a `.env` in the preview dir with a **distinct** project/host so it
   doesn't collide with the running instance:
   ```
   SERVICE_NAME=<service>-<slug>
   SERVICE_HOST=<service>-<slug>.servyy-test.lxd
   TRAEFIK_ENTRYPOINT=web
   TRAEFIK_TLS=false
   TRAEFIK_CERTRESOLVER=
   BUMBLEFLIES_HOST=
   ```
   (On servyy-test there is no real ACME, so TLS is off and the bf/http
   routers must resolve to nothing — same as the testing inventory overrides.)
4. Copy the rendered secrets env (e.g. `web.env`) and fix `PUBLIC_BASE_URL` to
   the preview host:
   ```bash
   ssh servyy-test.lxd "cp /home/cda/servyy-container/<service>/web.env /home/cda/servyy-container/<service>-preview/web.env"
   ```
   Then edit the copy so `PUBLIC_BASE_URL=http://<service>-<slug>.servyy-test.lxd`.
5. **Isolate data:** the compose hardcodes `DATABASE_URL` to
   `<project>.mongo`. Under a different project name that resolves to the
   *production* mongo. Repoint the app's `DATABASE_URL` in the preview
   compose to the compose-internal service name `mongo`
   (`mongodb://mongo:27017/<service>`), and keep the `mongo` sidecar +
   its own volume in the preview compose so preview data never touches prod.
6. Build the branch image with a **distinct tag** (so it can't clash with the
   running instance's tag):
   ```bash
   ssh servyy-test.lxd "cd /tmp/<svc>-build && docker build -t <service>:<slug> ."
   ```
   and set the preview compose's `image:` to `<service>:<slug>`.
7. Bring it up:
   ```bash
   ssh servyy-test.lxd "cd /home/cda/servyy-container/<service>-preview && docker compose up -d"
   ```

## Step 4 — Verify

```bash
IP=$(lxc list servyy-test --format json | jq -r '.[0].state.network.eth0.addresses[]|select(.family=="inet")|.address'|head -1)
# replace mode:
curl -s -H "Host: <service>.servyy-test.lxd" http://$IP/health
# preview mode:
curl -s -H "Host: <service>-<slug>.servyy-test.lxd" http://$IP/health
```
Both should return `{"status":"ok"}` (or the service's health shape), routed
through `traefik.traefik`. Also:
```bash
ssh servyy-test.lxd "docker ps --filter name=<service>.web --format '{{.Names}} {{.Status}}'"
ssh servyy-test.lxd "docker logs --tail 20 <service>.web"
```

## Step 5 — Confirm the local build was used (not a registry pull)

```bash
ssh servyy-test.lxd "docker inspect --format='{{.Image}}' <service>.web"
```
Must equal the image ID from Step 2. If it differs, compose pulled from the
registry instead — stop and investigate (tag mismatch / `--pull` behavior).

## Cleanup

- Build dir: `ssh servyy-test.lxd "rm -rf /tmp/<svc>-build"`.
- Preview stack: `ssh servyy-test.lxd "cd /home/cda/servyy-container/<service>-preview && docker compose down -v"` (the `-v` also drops the preview's isolated mongo volume).

## Gotchas

- **Never run `docker` locally** — only on `servyy-test.lxd`. The laptop has no Docker.
- **Image tag must match the compose** for replace mode, or compose pulls from
  the registry and you silently deploy the wrong (or stale) image.
- **Secrets** come from the Ansible-rendered env file on host (git-crypt in the
  repo). Don't hand-author `web.env`; copy the rendered one.
- **`job-search` owns host port 27017** on the shared host — dontforget's mongo
  stays internal (no published port), so don't add a host port mapping.
- **servyy-test IP can change** if the LXD container is recreated — re-derive
  `$IP` rather than caching it.
- **Replacing** recreates only the app container; the db volume persists. Use
  **preview** when you must not disturb the running instance.
- **Traefik routers collide** if two stacks share a `SERVICE_NAME`/`SERVICE_HOST`
  — that's why preview uses a slug-suffixed name/host.
