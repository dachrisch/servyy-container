# dontforget First Deployment (servyy-test only)

**Date:** 2026-08-09
**Status:** ✅ Verified working on `servyy-test.lxd`. **Not deployed to production** — stopped for approval per instructions.
**Branches:** `claude/dontforget-deploy` in both `dontforget` (app repo) and `servyy-container` (this repo)
**dontforget repo:** `github.com:dachrisch/dontforget.git`

## Problem

`dontforget` (recurring-event reminder service — search once, get a calendar feed of dates found)
was fully built and manually verified via `npm run dev`, but had no way to run outside a
developer's laptop: no `Dockerfile`, no image-publishing CI, no Ansible service wiring in this repo.

## Solution

### dontforget repo (app side)

- `Dockerfile` — multi-stage build (`node:24-alpine`). Installs+builds both npm packages (root
  backend via `tsc`, `web/` frontend via `vite`), then a slim runtime stage with only production
  `node_modules` + compiled `dist/` + `web/dist/`. Non-root (`USER node`). `HEALTHCHECK` uses
  Node's built-in `fetch` against `GET /health` (no curl/wget needed in alpine).
- `.github/workflows/part_docker_{build,test,push_artifact}.yaml` (new) — modeled on
  `ai-job-search`'s reusable workflows (build→artifact→health-test→push), simplified since
  dontforget doesn't need a pre-build bundling step or version build-args. Pushes to
  `docker.io/dachrisch/dontforget`, tags `latest` + the git ref name (no semver/release-please
  automation exists for this repo yet, unlike ai-job-search, so semver tag patterns would
  silently produce nothing).
- `.github/workflows/ci.yaml` (extended) — the existing tag-triggered workflow (previously
  build+test only) now chains `docker-image → image-test → image-push` after the existing
  `node-project`/`web-project` jobs.
- **Real bug found and fixed during servyy-test verification** (not an infra issue —
  `src/**/*.ts`): `tsconfig.json`'s `moduleResolution: "Bundler"` lets `tsc` accept extensionless
  relative imports (`from './app'`), but `tsc` doesn't rewrite them on emit, and Node's own ESM
  loader (unlike `tsx` in dev or `vitest` in tests, both of which resolve extensionless imports
  themselves) requires the literal `.js` extension. `dist/server.js` crash-looped with
  `ERR_MODULE_NOT_FOUND` on first deploy. This had never surfaced before because this was the
  first time the compiled output was run with plain `node` instead of `tsx`/`vitest`. Fixed by
  adding `.js` to every relative import across `src/` (valid syntax under `"Bundler"` resolution
  too — no tsconfig/bundler change, no behavior change). All 32 tests still pass.

### servyy-container repo (infra side)

- `dontforget/docker-compose.yml` (new) — one app container (`web`, image
  `dachrisch/dontforget:latest`, serves both API and built frontend — single container, not a
  split frontend/api pair) + one internal-only `mongo` container (named volume, healthcheck,
  `depends_on: condition: service_healthy`). Modeled on `job-search`'s shape, simplified to one
  app container since dontforget's backend already serves the built frontend itself. Traefik
  labels use `${SERVICE_NAME}`-templated router names (matches this repo's own "Adding a New
  Service" convention and `leagues-finance`/`opencode`'s style, not `job-search`'s hardcoded
  names).
- `ansible/plays/roles/docker_service/templates/dontforget/{.env.j2,web.env.j2}` (new) —
  `.env.j2` carries `SERVICE_HOST`/`SERVICE_NAME`/`TRAEFIK_*` (needed for docker-compose's own
  `${VAR}` label interpolation, which only reads the actual `.env` file, not `env_file:` entries).
  `web.env.j2` carries the app's runtime secrets: `PUBLIC_BASE_URL` (protocol computed from
  `TRAEFIK_TLS` so it's `http://` on test, `https://` in prod), `SEARXNG_BASE_URL` (static —
  always the real `search.lehel.xyz`, matching `job-search`'s convention of never having a
  test-specific searxng), `SEARXNG_TOKEN` (reuses `vault_searxng_brave_token`), `OPENCODE_BASE_URL`
  (dynamic — `opencode.{{ inventory_hostname }}`, since opencode itself *is* deployed per-host
  unlike searxng), `OPENCODE_API_KEY` (reuses `opencode.api_key`, same secret opencode-authgate
  already uses). `SMTP_*` deliberately absent — no transactional email provider chosen yet
  (`docs/design.md` §8 in the dontforget repo); the app falls back to logging the magic link to
  stdout.
- `ansible/plays/user.yml` — new `docker_service` role invocation, tags
  `[user.docker, user.docker.dontforget]`. `service_host` left at its default
  (`dontforget.{{ inventory_hostname }}`) — no override needed, unlike `job-search`'s custom
  `jobs.*` subdomain.
- `ansible/plays/roles/user/tasks/docker_extras.yml` — registered in the
  `forall_docker_services.sh` service list, after `job-search`.
- `ansible/testing` — `dontforget_traefik_{entrypoint,tls,certresolver}` overrides
  (`web`/`false`/empty) for `servyy-test.lxd`, same pattern as `searxng`/`job-search`'s test
  entries (this host has no real Let's Encrypt DNS resolver for these subdomains). Did **not**
  add a `dontforget_service_host` var — checked, and the equivalent `searxng_service_host`/
  `job_search_service_host` vars already in this file are unused anywhere in the codebase
  (`service_host` is always computed inline in `user.yml`, never through a host_var
  indirection) — no point adding more dead config.

### DATABASE_URL / NODE_ENV / PORT

Set directly in `docker-compose.yml`'s `environment:` block (not templated) — they're not
secrets and don't vary by host: `DATABASE_URL=mongodb://mongo:27017/dontforget`,
`NODE_ENV=production`, `PORT=3000`.

## Deployment mechanics (worth recording — no registry image existed yet)

The dontforget GitHub repo has **no `DOCKER_TOKEN` secret configured yet** (checked via
`gh api repos/dachrisch/dontforget/actions/secrets` — empty, unlike `ai-job-search` which has
one). I don't have the Docker Hub token value, so I couldn't set it myself, and therefore
couldn't trigger the real CI publish path for this first deployment. To verify the actual
deployment mechanics today rather than block on that:

1. Pushed both feature branches (`dontforget`'s and this repo's `claude/dontforget-deploy`) to
   their GitHub origins.
2. `git clone`d the dontforget branch directly onto `servyy-test.lxd` (`/tmp`, cleaned up after)
   and ran `docker build -t dachrisch/dontforget:latest .` there — Docker only ever ran on
   servyy-test, never locally, per this repo's hard rule.
3. Ran the real deploy path unmodified: `ansible/servyy-test.sh --tags
   "user.docker.repo,user.docker.dontforget"` — this syncs `servyy-container` itself onto the
   host (git-crypt unlock included) at the branch checked out locally, then renders envs and
   runs `docker_compose_v2` for just the `dontforget` service. Because the image tag already
   existed locally on servyy-test from step 2, Compose used it directly without attempting a
   registry pull.

**Before this can go through the real CI pipeline** (needed before it can ever reach
production, since production has no local pre-built image), someone with the Docker Hub
credentials needs to run:
```
gh secret set DOCKER_TOKEN --repo dachrisch/dontforget
```
using the same Docker Hub access token already used for `ai-job-search` (or a new one scoped to
the `dachrisch/dontforget` repository on Docker Hub), then push a tag to trigger
`.github/workflows/ci.yaml`.

## Verification (servyy-test.lxd)

- `docker ps`: `dontforget.web` — healthy; `dontforget.mongo` — healthy (internal network only,
  no host port, confirmed no conflict with the pre-existing ad-hoc `dontforget-mongo`/
  `dontforget-mongo-dev` dev-database containers on ports 27018/27019).
- `curl -H 'Host: dontforget.servyy-test.lxd' http://localhost/health` → `{"status":"ok"}`,
  HTTP 200, routed through `traefik.traefik` correctly (entrypoint `web`, no TLS, matching the
  test-inventory override).
- `curl -H 'Host: dontforget.servyy-test.lxd' http://localhost/` → HTTP 200 (built frontend
  served statically from the same container).
- **Full sign-in round trip:** `POST /api/auth/magic-link` → 202 → magic link printed to
  `docker logs dontforget.web` (`ConsoleEmailSender` fallback, as expected with no `SMTP_*`
  configured) → followed the callback URL → `302` + `Set-Cookie: df_session=...` → `GET /api/me`
  with that cookie → `{"authenticated":true}`, HTTP 200. Without the cookie, `/api/me` correctly
  returns 401.
- Mongo: `runMigrations` applied `001_init.ts` on first boot (`schema_migrations` collection has
  one entry), all 7 expected collections present.

## Known gaps (not blockers for this test deployment)

- No real transactional email — `SMTP_*` unset by design, magic links only reach the console
  log. Tracked as an open item in the dontforget repo's own design doc.
- `DOCKER_TOKEN` secret not yet set on the dontforget GitHub repo — the CI image-publish path is
  wired but unexercised; today's servyy-test image was built directly on the host instead (see
  above).
- Production (`lehel.xyz`) deployment intentionally not attempted — stopped here per explicit
  instruction, pending review/approval of this branch.
