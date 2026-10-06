# 2026-10-06 queen CI/Docker publish + shared data-layer consolidation (test + prod)

Two repos, one day. `bumbleflies/queen` went from plan-only to scaffolded with a
working release pipeline (`queen-v0.2.0` published to `bumblecode/queen`);
`servyy-container` gained a consolidated `shared` data compose, slimming the
`leagues-finance` and `finance` projects. Deployed to servyy-test (shared +
queen) and production (shared; queen gated off). Merged to master the same day.

## Part 1 — queen repo: scaffold, CI, first release

- **Scaffold** (`74658ab chore: scaffold bumbleflies/queen`, plan Task 1): deps
  cloned from `leagues.finance/package.json` minus `mysql2` (also dropped
  `@playwright/test`, added `supertest`), `tsconfig.json` /
  `tsconfig.server.json` / `vite.config.ts` / `vitest.config.ts` copied,
  `src/server/{index,app,health}.ts` + `db/mongo.ts` (in-memory fallback),
  supertest `GET /health → 200` test, placeholder client (UI deferred — a mock
  is built separately). `typecheck` + `typecheck:server` + `test` pass.
  Follow-up fix: `tsconfig.server.json` needed explicit `"rootDir": "."`
  (TS 7 TS5011 — no `shared/` dir exists yet to anchor the common root).
- **CI + Docker publish** (`c6c29a6`, `db3395d`): migrated from
  `bumbleflies/edu`, not leagues.finance. Reference hunt went
  leagues.finance → `web` → `edu`; findings: org namespace is `bumblecode/*`
  (plan doc was right, leagues.finance's `dachrisch/*` is the outlier),
  registry login is `DOCKERHUB_USERNAME` + `DOCKER_TOKEN`, releases use a
  GitHub App (`RELEASE_PLEASE_APP_ID` + `RELEASE_PLEASE_APP_PRIVATE_KEY`,
  tags `queen-v*`), `renovate.json` copied from edu verbatim.
  `Dockerfile` is the one leagues.finance-derived file (Node 24 multi-stage,
  non-root `node`, `/health` HEALTHCHECK).
- **Secrets incident**: the first `RELEASE_PLEASE_APP_ID` value supplied was a
  32-hex client *secret*, not a client ID (`Iv1…` shape) → `404 Integration
  not found`. Fixed with the real client ID; rerun went green.
- **Release train verified end to end**: empty `feat:` commit → release-please
  PR #3 → auto-merge → tag `queen-v0.2.0` → `release.yml` published
  `:latest` + semver + sha to Docker Hub.
- `AGENTS.md` created (plan-doc pointer, scaffold contract, six code
  invariants) and extended with the CI/publish section.

## Part 2 — shared data-layer consolidation (servyy-container)

**Decision trail**: queen-in-finance-compose → queen-in-leagues-finance-compose
(reuse its mongo) → back to finance (Firefly proximity, plan-doc home) →
final: new **`shared` compose** holding mongo + valkey + postgres, apps
attach via external `shared_backend`. Full consolidation *now* (not phased):
everything is recoverable today, and the mongo volume moves by *name
adoption* (`name: leagues-finance_mongo_data`), postgres by identical bind
path — zero dump/restore, downtime is restarts only.

**Branch** `claude/queen-shared-consolidation` → merged to master as `4c1e392`
(12 files). Contents:
- `shared/docker-compose.yml` (new, backend-only, no Traefik): mongo + valkey
  (prod-proven pinned digests, same root creds = zero rotation) + postgres.
- `leagues-finance/docker-compose.yml` slimmed (mongo/redis/volume dropped;
  joins external `shared_backend`; `.env.j2` hosts → `shared.mongo` /
  `shared.redis`).
- `finance/docker-compose.yml` slimmed (`db` dropped, `DB_HOST: shared.db`)
  plus the **`queen` service** (`bumblecode/queen:latest`, searxng-style
  `${TRAEFIK_*}` labels, Ofelia 07:30 reconcile labels).
- Ansible: `templates/shared/.env.j2`, `templates/finance/queen.env.j2`
  (mongo db `queen`, redis db `1` — leagues-finance owns db `0`; Google/Firefly
  values reused with comments), `queen:` secrets (fresh JWT + service token),
  `docker_service` subset support (`compose_services`, empty = all), `shared`
  role block ordered before apps, `finance_services` prod gate (excludes
  queen), test inventory runs `shared[mongo,redis]` + `finance[queen]`.
- **Safety fixes found during planning, before prod**: (1) compose never
  removes orphans → one-time removal of `leagues-finance.mongo` /
  `leagues-finance.redis` / `finance.db` (containers only) or two mongos
  write one volume; (2) the mongo wipe-guard post-task would have fired on the
  missing `leagues-finance.mongo` and **deleted the data volume** → retargeted
  to `shared.mongo`/`shared` project; (3) legacy FCV post-task exec gated to
  the 7→8 upgrade path only; (4) broken `ansible/production` edit (split
  mapping) caught by `--syntax-check` before any run.

**Test deploy** (`./servyy-test.sh --tags
user.docker.shared,user.docker.finance,user.docker.env.finance`, 0 failures):
`shared.mongo` / `shared.redis` / `finance.queen` healthy; queen log shows
`connected: shared.mongo:27017`; `/health` → ok; `queen.env` rendered
test-correct. Queen reached the branch via the `id_servyy_container_deploy`
key (`GIT_SSH_COMMAND`), since the test host has no GitHub SSH auth otherwise.

**Prod deploy** (explicit approval, same narrow tags + leagues-finance):
`shared.{mongo,redis,db}` healthy, `finance-api` log confirms
`connected: shared.mongo:27017`, `finance.firefly` healthy and serving via
Traefik. Data verified intact: mongo `leagues_finance` byte-identical
(1224704), postgres `migrations` = 61, orphans gone, **0 queen containers**
(gate holds). Both servers switched back to `master`.

## Known gaps / follow-ups

- Traefik route for queen unverified on test (no Traefik there; `*.servyy-test.lxd`
  DNS points at .233 elsewhere). Proven pattern only; first real proof is prod.
- Empty `leagues-finance_internal` network lingers on prod (harmless).
- Implementing session constraints: Bull queues must use redis db `1`+ (db `0`
  is leagues-finance's); Firefly neighbor for reconcile is free once queen is
  enabled on prod (`http://finance.firefly:8080`).
- Stray one-line deletion appeared in `docker_extras.yml` mid-session from an
  unknown party; reverted to keep the branch clean.
- Secrets set on `bumbleflies/queen` (GitHub only, never in git):
  `DOCKERHUB_USERNAME`, `DOCKER_TOKEN`, `RELEASE_PLEASE_APP_ID`,
  `RELEASE_PLEASE_APP_PRIVATE_KEY`. Chat transcript contains the raw values —
  rotate if it ever leaves trusted hands.
