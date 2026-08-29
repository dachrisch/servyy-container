---
name: bootstrapping-bumbleflies-subdomain
description: Use when standing up a new bumbleflies-family static site as a subdomain (e.g. *.bumbleflies.de) — creating its GitHub repo, Astro scaffold, Docker/CI pipeline, and servyy-container routing from scratch.
---

# Bootstrapping a bumbleflies Subdomain Project

## Overview

Every bumbleflies subdomain project (bricksnbytes.bumbleflies.de, edu.bumbleflies.de, ...)
follows the same five-step recipe: GitHub repo, Astro static scaffold, Docker/nginx,
a 5-file GitHub Actions CI pipeline, and a service block added to the *existing*
shared `bumbleflies/docker-compose.yml` in this repo (`servyy-container`).
This skill is infra-only — it does not cover building the actual site content.

## When to Use

- Starting a new bumbleflies-family project that needs to live at `<name>.bumbleflies.de`.
- Symptoms: "set up a new bumbleflies project", "add a subdomain to bumbleflies",
  "deploy a new site under bumbleflies.de".
- NOT for: adding pages/features to an *existing* bumbleflies subdomain (that's
  normal development, not bootstrap), or any non-bumbleflies project.

## Steps

1. **GitHub repo** — `gh repo create bumbleflies/<name> --public --description "..." --source=. --remote=origin`
   after `git init -b master` in the target directory, so the default branch is
   `master` from the very first push (the org convention — `main` will break the
   CI trigger conditions and the servyy-container branch lookup below).

2. **Astro scaffold** — hand-write the minimal set rather than relying on the
   `create-astro` CLI's interactive prompts: `package.json` (dev/build/preview/test
   scripts, `astro` + `@astrojs/check` + `typescript` + `vitest`), `tsconfig.json`
   (`extends: astro/tsconfigs/strict`), `astro.config.mjs`
   (`output: 'static'`, `outDir: 'dist'`), `src/env.d.ts`, `src/pages/index.astro`,
   one trivial Vitest smoke test. **Put the test outside `src/pages/`** (e.g.
   `src/index.test.ts`, not `src/pages/index.test.ts`) — Astro treats every
   `.ts`/`.js` file under `src/pages/` as a route/endpoint, so a colocated
   test file gets picked up as a page and crashes `astro build` trying to
   render vitest's `describe()` as route code. `npm install`, `npm run build`,
   `npx astro check`, `npm run test` must all pass before the first commit.

3. **Docker/nginx** — pick one existing sibling project as your reference for
   this and the next step (e.g. `/home/cda/dev/bricksnbytes`, or the most
   recently bootstrapped one — `bumbleflies/edu` as of 2026-08-24) and copy
   `Dockerfile` and `nginx.conf` from it verbatim: multi-stage `node:24-alpine` builder →
   `nginx:alpine` runtime, `HEALTHCHECK` hitting `/health`, nginx config serving
   `dist/` with gzip + a `/health` endpoint. Also copy `renovate.json` so dependency
   automation matches the rest of the org. `docker build` + `docker run` locally,
   poll `docker inspect --format='{{.State.Health.Status}}'` until `healthy`.

4. **CI/CD** — copy the same sibling project's 5-workflow set verbatim,
   changing only `IMAGE_NAME` in `build-publish.yml` to `bumblecode/<name>`:
   `pr-tests.yml` (reusable: `npm ci`, `npm run test`, `npx astro check`),
   `pr.yml` (PR → calls `pr-tests.yml`), `push.yml` (non-master push → calls
   `pr-tests.yml`), `master.yml` (master push → `pr-tests` then
   `build-publish.yml` with `secrets: inherit`), `build-publish.yml` (build →
   healthcheck-smoke-test → push to Docker Hub via `secrets.DOCKER_TOKEN`).
   **`DOCKER_TOKEN` is already an org-level GitHub secret** — do not create a
   repo secret for it; a brand-new repo in the org inherits it automatically.
   Push and `gh run watch --repo bumbleflies/<name>` until the `Master Workflow`
   run is green — this is also how you confirm the image actually landed on
   Docker Hub, without needing Docker Hub credentials to check directly.

5. **servyy-container routing** — in *this* repo (`servyy-container`, not the
   site's own repo), add a new service block to the **existing**
   `bumbleflies/docker-compose.yml` (do not create a new top-level service
   directory or a new Ansible role — `service_dir: bumbleflies` in
   `ansible/plays/user.yml` already deploys this whole file). Model the new
   block on the `bnb` block already in that file:
   `image: bumblecode/<name>:latest`, a Traefik router keyed to
   `Host(\`<name>.bumbleflies.de\`)` with `certresolver=letsencrypthttpresolver`,
   a local-qualified router for dev/test (`Host(\`<name>.${SERVICE_NAME}.${LOCAL_HOSTNAME}\`)`),
   `com.centurylinklabs.watchtower.scope=dev`. `${SERVICE_NAME}` and
   `${LOCAL_HOSTNAME}` aren't yours to define — they're existing env vars the
   `docker_service` Ansible role already renders into every service's `.env`
   file (`service_dir`-derived and per-inventory respectively); just reference
   them the same way the `bnb`/other blocks in the same file already do.

   Before deploying: **commit on a feature branch and push it to `origin`.**
   The Ansible play clones this repo onto the target host using
   `git -C <local_dir> rev-parse --abbrev-ref HEAD` as the branch to fetch — i.e.
   whatever branch is checked out **locally right now**, fetched from `origin`.
   If you only commit locally without pushing, the deploy silently redeploys the
   old `master` state.

   Deploy: `cd ansible && ./servyy-test.sh --tags "user.docker.repo,user.docker.bumbleflies"`
   — prefer this narrower pair over the broad `--tags user.docker`. The repo tag
   gets your branch cloned onto the host; the `bumbleflies` tag redeploys just
   that shared compose file (now including your new block). The broad tag
   redeploys *every* docker service on the test host, including any unrelated,
   already-flaky one (observed in practice: an unrelated service failed on a
   stale mount and blocked the whole run before it ever reached `bumbleflies`)
   — the narrow pair sidesteps that risk entirely, at no cost since these are
   the only two tags this task's deploy ever needed. Never `servyy.sh` /
   `--limit lehel.xyz` — that's production, and requires separate explicit user
   approval per this repo's CLAUDE.md. Verify with
   `ssh servyy-test.lxd "docker ps | grep bumbleflies.<name>"` and a `curl` against
   the local-qualified host.

   After test verification, open a PR against `master` for the feature branch
   (this repo's normal workflow — dev branches get PR'd and merged, they don't
   land on `master` via direct push). Production deployment still requires a
   separate, explicit approval — merging the PR only makes the change part of
   `master`'s history, it doesn't deploy it to `lehel.xyz` by itself.

   If the local checkout was already on some other branch when you started
   (someone else's in-progress work), don't branch from whatever's currently
   checked out — `git fetch origin && git checkout -b claude/<name>-service
   origin/master` instead, so unrelated history doesn't leak into your commit,
   and restore the original branch checkout as a courtesy once you're done
   (the deploy needs your branch checked out locally only while it runs —
   Ansible reads the local checkout's current branch name to decide what to
   fetch from `origin`).

## Common Mistakes

| Mistake | Fix |
|---|---|
| Letting `gh repo create` pick GitHub's current default branch | `git init -b master` locally *before* creating/pushing, so it's `master` from commit zero |
| Colocating a Vitest smoke test under `src/pages/` | Astro treats every `.ts` file there as a route and crashes the build — put tests at `src/index.test.ts` or similar, outside `src/pages/` |
| Creating a new top-level `servyy-container` service directory / Ansible role for the subdomain | Add a service block to the *existing* `bumbleflies/docker-compose.yml` instead — `service_dir: bumbleflies` already covers it |
| Running `servyy-test.sh` right after `git commit` (no push) | Push the branch to `origin` first — the target host clones from `origin`, not your local working tree |
| Deploying with the broad `--tags user.docker` | Redeploys every service on the test host, including unrelated flaky ones. Use `--tags "user.docker.repo,user.docker.bumbleflies"` to touch only what this task needs |
| Assuming a new repo needs its own `DOCKER_TOKEN` secret | It's an org-level secret already inherited by every bumbleflies repo |
| Naming any compose service `app` | Causes DNS ambiguity across the shared `proxy` network — always use a descriptive name |
| Deploying to `lehel.xyz` without being asked | Production always requires a separate, explicit approval — this recipe only covers `servyy-test.lxd` |
| Leaving the feature branch pushed but un-PR'd | This repo merges dev branches via PR, not direct push to master — open one once the test deployment is verified |

## Real-World Impact

Used to bootstrap `edu.bumbleflies.de` (2026-08-24) following the exact prior
pattern of `bricksnbytes.bumbleflies.de` — GitHub repo, Astro scaffold, Docker/CI,
and a `servyy-container` service block, verified end-to-end on `servyy-test.lxd`.
