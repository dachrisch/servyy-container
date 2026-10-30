# 2026-10-30 — Image tags: float what was starving for patches

**Date:** 2026-10-30
**Status:** ✅ Deployed on `servy.lehel.xyz` and `codey.lehel.xyz` (opencode on codey still
pending — see Known Issues)
**Relates to:** `2026-10-29_traefik-3.7-upgrade.md`, `2026-10-29_exposure-guards.md`,
`2026-10-29_exposure-triage.md`, PR #249

## Context

An audit of every deployed compose file (24 files, 50 image references) showed the fleet
mostly floating (`:latest`, `dachrisch/*`, `bumblecode/*`) with a small, load-bearing set
pinned by hand: traefik, error-pages, pushgateway, moodle, opencode, watchtower, and four
database digests.

The pins were not buying anything. **Watchtower re-pulls the tag a container already has**
— it never moves a container to a different tag — so a pinned tag only changes when a
deploy runs, and the pins were measurably stale:

| container | running | repo said | merged |
|---|---|---|---|
| `monitor.pushgateway` | `v1.6.2` | `v1.11.5` | #243, 2026-10-30 |
| `opencode.web` (codey) | `2.1.2` | `2.2.2` | #242, 2026-10-30 |

`traefik:3.6.1` had already sat through ~24 patch releases before #234 bumped it by hand.
So the pinning policy was inverted: the images that matter most for security fixes were
the ones that never moved, while everything else updated itself every two hours.

## Decision

Float where a patch release is a security fix and a break is recoverable. Every
replacement tag was checked against the registry first — four of the "obvious" floats do
**not exist**, which is why several services got `latest` rather than a `X.Y` line.

| file | before | after | why |
|---|---|---|---|
| `traefik/` | `traefik:3.7.16` | `traefik:3.7` | patch line only; static config is parsed strictly, so never cross a minor on its own |
| `traefik/` | `error-pages:4.2.7` | `error-pages:4.2` | template renderer, patches uneventful |
| `monitor/` | `pushgateway:v1.11.5` | `pushgateway:latest` | Prometheus images publish no `vX.Y` tag (verified 404) |
| `opencode/` | `opencode:2.2.2` | `opencode:latest` | no `2` / `2.2` tag exists; `latest` does |
| `portainer/`, `portainer-agent/` | `watchtower:1.19.0` ×4 | `watchtower:latest` | only `latest` exists upstream |
| `bnb-office/`, `moodle/` | `mariadb@sha256:2bdff15…` | `mariadb:12.3` | the digest was **12.3.3**; a digest freezes even Debian/MariaDB patches |
| `shared/` | `mongo:8@sha256:e0ce…` | `mongo:8` | digest froze patch fixes |
| `shared/` | `valkey/valkey:9-alpine@sha256:ee91…` | `valkey/valkey:9-alpine` | same |

**A near miss worth recording:** the first draft of this change said `mariadb:11.8`, from
the assumption that the pinned digest was an 11.x build. It is `12.3.3` — 11.8 would have
been a **major downgrade**, which MariaDB cannot do on an existing data directory, on
both `bnb-office.db` and `moodle.db`. The version was read out of the running containers
(`mariadb --version`) rather than inferred from the digest.

Deliberately still fixed: `moodle:erseco/alpine-moodle:v4.5.15`, and every DB **major**
line (`postgres:15`, `mongo:8`, `valkey:9`). `mariadb` containers carry no
`watchtower.scope` label, so their floats land on deploy, not unattended.

## Verification

- `yaml.safe_load` on all 8 edited files — parses
- `yamllint -c .yamllint.yml` — the 10 findings are identical to `origin/master`; compared
  as parsed rule/severity output, not by count
- registry lookup for every proposed tag (Docker Hub v2 API and the ghcr manifest API)
- `traefik:3.7` and `traefik:3.7.16` resolve to the **same digest**, so the traefik tag
  change was a version no-op; `traefik version` on both hosts confirms `3.7.16`
- `mariadb:12.3` is the same build: both DBs report `12.3.3-MariaDB` after recreate, and
  `moodle.db`/`bnb-office.db` came up healthy
- `pushgateway:latest` → `1.11.5`, closing the `v1.6.2` drift
- `watchtower:latest` still resolves to `1.19.0` today
- post-deploy sweep: git, leaguesphere, moodle, finance, monitor, pass, bnb-office, both
  traefik dashboards — all expected status codes, HSTS still present, no `level=error` in
  the traefik or DB logs

## Known issues found while deploying

1. **codey's disk was 100 % full** (29 G, 0 B free) — the deploy aborted with
   `FileNotFoundError: No usable temporary directory`. The bulk is the `opencode.web`
   container's **writable layer (3.9–5.6 G, most of it `/tmp`)**, on top of the
   `opencode_opencode_root` (5.5 G) and `codey_dev_checkouts` (4.8 G) volumes.
   Freed **~5.3 G** (0 B → 5.3 G free, 81 % used) by deleting regenerable caches and
   scratch after confirming no process held a cwd or open file in them:
   `/root/.cache/{puppeteer,mongodb-binaries}` (1.1 G), `npm cache clean` (0.7 G),
   day-old `/tmp/opencode/{vitest5,ovr-fix,reb,pil,pdfenv}` (1.8 G), apt cache, and the
   disabled `canonical-livepatch` snap.
   **Not fixed, only bought time.** Left untouched on purpose: `/root/dev` (4.8 G of
   another session's checkouts — three live sessions had cwds inside it),
   `/root/.local/share/opencode` (1.9 G of session state), and
   `/root/.cache/ms-playwright` (0.7 G, in use). The durable fixes are a recreate of
   `opencode.web` at a quiet moment (drops the whole writable layer) plus pruning the
   stale checkouts — realistically 2.7 G of the 4.8 G is not in use by anyone.

2. **Vaultwarden pushes are broken from the controller** — `bw login --apikey` fails
   against `pass.lehel.xyz` with the credentials in `vars/secrets.yml`, and
   `bw unlock` with `~/.ssh/vw.key` fails too. This blocks any deploy that includes
   `user.docker.traefik` (its post-task pushes the dashboard password to Vaultwarden) or
   `user.opencode` (pushes the server password and SSH key). Worked around for this
   rollout with `--skip-tags user.opencode -e traefik_dashboard_push_vaultwarden=false`;
   the pushes are convenience copies, the git-crypt'd seeds remain the source of truth.
   **Rotating or re-issuing the API key is outstanding.**
3. **`opencode:latest` is committed in the repo but not deployed.** codey had live
   `opencode serve` sessions (MCP servers spawned minutes earlier) while this ran, and
   recreating that container would have killed them. The tag only takes effect at the
   next recreate, so the container keeps re-pulling `2.1.2` until then.
4. Meh: `/tmp/opencode-superpowers-upstream` on the controller had a deleted working tree
   (`git reset --hard` restored it) and the opencode role's skills/templates rewrote
   themselves during the retries — both benign, both silent until a deploy fails.
