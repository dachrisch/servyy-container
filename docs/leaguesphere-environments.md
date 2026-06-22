# LeagueSphere — Environments & Deployment Reference

> One-stop reference for the **prod**, **stage**, **demo**, and **test** deployments of
> LeagueSphere, how to set each one up, where their logs/metrics live, and the two everyday
> playbooks: **investigate an error on prod** and **reproduce it with real data**.
>
> Deployment is driven from this repo's Ansible (`ansible/plays/leaguesphere.yml` and the
> `ls_*` roles). The application code lives in the separate `leaguesphere` repo
> (`github.com/dachrisch/league-manager`).

---

## TL;DR — the everyday workflows

```bash
# ── Investigate an error on PROD ────────────────────────────────────────────
ssh lehel.xyz "docker logs leaguesphere.app --tail 100"      # Django backend
ssh lehel.xyz "docker logs leaguesphere.www --tail 100"      # static frontend / nginx
# then open Grafana → https://monitor.lehel.xyz  (dashboard: "leaguesphere")
#   and/or query Loki for {container="leaguesphere.app"} — see "Logs & metrics" below

# ── Reproduce it with REAL prod data ────────────────────────────────────────
# The ls_db_sync role clones prod into the STAGE stack. Deploy that stack on whichever
# host you want, then sync:
cd ansible
./servyy.sh      --tags ls.db.sync --limit lehel.xyz   # → public stage on lehel.xyz
#   ── or, into the isolated TEST box ──
./servyy-test.sh --tags ls.db.sync                     # → stage stack on servyy-test.lxd
```

> 💡 **What `ls_db_sync` actually does:** it clones the **production database into the _stage_
> stack** (`leaguesphere_stage.mysql`). Because the playbook is `hosts: all` with no host
> gating, that stage stack — and the sync — runs against **whatever inventory you target**:
> `./servyy.sh` puts it on `lehel.xyz` (public `stage.leaguesphere.app`); `./servyy-test.sh`
> puts it on `servyy-test.lxd` (a fully isolated copy with prod data). Either way you get a
> real-data reproduction; pick the host by how isolated you need to be.
>
> This is **separate** from `spinup_test_db.sh`, which seeds a lighter `mysql` container on
> `servyy-test.lxd` with **synthetic** fixtures for the pytest suite (see
> [Test](#4-test--servyy-testlxd)). Use `ls_db_sync` for real-data repro, `spinup_test_db.sh`
> for running the test suite.

---

## Environment matrix

| | **Prod** | **Stage** | **Demo** | **Test** |
|---|---|---|---|---|
| URL | `leaguesphere.app` | `stage.leaguesphere.app` | `demo.leaguesphere.app` | — (no public app) |
| Host | `lehel.xyz` | `lehel.xyz` (same host) | `lehel.xyz` | `servyy-test.lxd` (LXD) |
| Compose project | `leaguesphere` | `leaguesphere_stage` | `leaguesphere-demo` | `mysql` (DB only) |
| App container | `leaguesphere.app` | `leaguesphere_stage.staging-app` | `leaguesphere-demo.demo-app` | n/a |
| Web container | `leaguesphere.www` | `leaguesphere_stage.www` | `leaguesphere-demo.www` | n/a |
| Database | **external** MySQL `s207.goserver.host` (`web35_db8`) | container `leaguesphere_stage.mysql` (db `leaguesphere_stage`) | container `leaguesphere-demo.mysql` | container `mysql` (db `test_db`) |
| Data | live production data | **clone of prod** (via `ls_db_sync`) | synthetic, **auto-resets nightly** | synthetic fixtures (`test_db_dump.sql`) |
| Git branch | `master` | `master` | `master` | working tree (pytest) |
| Compose file | `deployed/docker-compose.yaml` | `deployed/docker-compose.staging.yaml` | `deployed/docker-compose.demo.yaml` | n/a |
| Deployed under | SSH chroot jail: `…/home/leaguesphere/container/` | jail: `…/container-stage/` | jail: `…/container-demo/` | n/a |

Container names follow this repo's convention `{project}.{compose-service}`, which is also the
**Loki `container` label** — see [Logs & metrics](#logs--metrics).

> **Stage is a stack, not a fixed host.** The "Stage" column above is the *public* stage on
> `lehel.xyz`, but the same stage stack (and its prod-data sync) can be deployed on
> `servyy-test.lxd` via `./servyy-test.sh` — an isolated, prod-data reproduction environment.
> See [Test › mode (b)](#4-test--servyy-testlxd).

---

## How it's wired (Ansible)

Everything runs from `ansible/plays/leaguesphere.yml`, imported by `ansible/servyy.yml`.

- **Inventories** (`ansible/`):
  - `production` → `lehel.xyz` (prod + stage + demo all live here)
  - `testing` → `servyy-test.lxd`
- **Run scripts** (`ansible/`):
  - `./servyy.sh` → `ansible-playbook servyy.yml -i production`
  - `./servyy-test.sh` → `ansible-playbook servyy.yml -i testing …`
- **Roles** (`ansible/plays/roles/`):
  - `ls_setup`, `ls_access` — shared host/user/jail setup (run once)
  - `ls_app` — deploys prod **and** stage (same role, different vars: `secret_main.yaml` vs `secret_stage.yaml`)
  - `ls_demo` — deploys the nightly-reset demo
  - `ls_db_sync` — clones prod DB → stage DB (details below)
- **Secrets / config** (git-crypt encrypted; appear as plaintext when the repo is unlocked):
  - `ansible/plays/roles/ls_app/vars/secret_main.yaml` — prod (DB host/name/user, secret key, Moodle, etc.)
  - `ansible/plays/roles/ls_app/vars/secret_stage.yaml` — stage
  - non-secret env is rendered from `templates/docker.env.j2` and `templates/ls.env.j2`

### Useful Ansible tags

`leaguesphere.yml` exposes granular tags so you don't redeploy everything:

| Tag | Scope |
|---|---|
| `ls` | everything LeagueSphere |
| `ls.app` | prod **and** stage app |
| `ls.app.prod` | prod only |
| `ls.app.stage` | stage only (also triggers `ls.db.sync`) |
| `ls.demo` | demo only |
| `ls.db.sync` | clone prod DB → stage (no redeploy) |
| `ls.app.pull` / `ls.app.env` / `ls.app.deploy` | sub-steps of an app deploy |

---

## Setup / deploy each environment

> **Deployment policy (this repo): test-first, no manual prod edits.** Validate on
> `servyy-test.lxd` first, never `scp`/`ssh`-edit prod files, and **ask for explicit approval
> before any production deploy.** See the repo `CLAUDE.md` › "CRITICAL DEPLOYMENT RULES."

### 1. Prod — `leaguesphere.app`

```bash
cd ansible
./servyy.sh --syntax-check                       # sanity check first
./servyy.sh --tags ls.app.prod --limit lehel.xyz # deploy prod app (after approval)
ssh lehel.xyz "docker ps | grep leaguesphere"    # verify
```
Backend pulls the `master` branch via sparse checkout and runs `deployed/docker-compose.yaml`.
The database is **external** (`s207.goserver.host`) — there is no prod DB container.

### 2. Stage — `stage.leaguesphere.app`

Stage **always deploys alongside prod** when you run `ls.app`, and the prod→stage DB sync runs
with it. To deploy stage on its own:

```bash
cd ansible
./servyy.sh --tags ls.app.stage --limit lehel.xyz
```
Stage runs `docker-compose.staging.yaml` with its **own** MySQL container
(`leaguesphere_stage.mysql`). On first boot the role removes the MySQL volume and runs the
init script so the `leaguesphere_stage` database is created automatically.

### 3. Demo — `demo.leaguesphere.app`

```bash
cd ansible
./servyy.sh --tags ls.demo --limit lehel.xyz
```
Demo uses pre-built images and **auto-resets nightly** — never put data you care about here.

### 4. Test — `servyy-test.lxd`

`servyy-test.lxd` is the LXD box used for testing. It serves **two distinct purposes** — don't
confuse them:

**(a) Run the pytest / molecule suites** against a light, synthetic-data MariaDB. This is a
single bare `mysql` container seeded from `test_db_dump.sql` — *not* the app stack.

**(b) Stand up a full prod-data reproduction** by deploying the **stage stack** here and syncing
prod into it (same `ls_app` + `ls_db_sync` roles as public stage, just targeted at the test
inventory):

```bash
cd ansible
./servyy-test.sh --tags ls.app.stage   # deploy stage stack on servyy-test + pull prod data
./servyy-test.sh --tags ls.db.sync     # later: re-pull fresh prod data
```
This gives you `leaguesphere_stage.*` containers on `servyy-test.lxd` holding a clone of prod —
fully isolated, nothing exposed publicly. (Stage host name derives from `inventory_hostname`,
i.e. `stage.leaguesphere.servyy-test.lxd`.) See
[Reproduce a prod issue with real data](#reproduce-a-prod-issue-with-real-data-ls_db_sync).

**Spin up / reset the pytest test DB** — purpose (a), run from the `leaguesphere` repo:
```bash
cd <leaguesphere-repo>
./container/spinup_test_db.sh --fresh   # recreates `mysql` container, imports test_db_dump.sql

# point pytest at it
export MYSQL_HOST=$(lxc list servyy-test --format json \
  | jq -r '.[0].state.network.eth0.addresses[] | select(.family=="inet") | .address' | head -n1)
pytest
```
The fresh import includes the **placeholder teams** that schedule JSON files reference (P1/P2/P3
groups, "Gewinner/Verlierer HF…", etc.). If you see `Team.DoesNotExist`, re-run with `--fresh`.

> This DB holds **synthetic fixtures, not production data.** To reproduce an issue against a
> real prod data shape, use **stage** + `ls.db.sync` (next section).

---

## Reproduce a prod issue with real data (`ls_db_sync`)

`ansible/plays/roles/ls_db_sync/tasks/main.yml` does, in order:

1. `mysqldump` the **prod** DB from `s207.goserver.host` (single-transaction, `--lock-tables=false`,
   **all views ignored**) into `/tmp/leaguesphere_prod_<epoch>.sql`.
2. Wait for `leaguesphere_stage.mysql` to be healthy.
3. **Drop & recreate** the `leaguesphere_stage` database (utf8mb4).
4. `docker cp` the dump in and import it.
5. Restart `leaguesphere_stage.staging-app`, then clean up the dump.

Run it against either host (the playbook is `hosts: all`, so the target is just the inventory):

```bash
cd ansible

# Public stage on lehel.xyz:
./servyy.sh --tags ls.db.sync --limit lehel.xyz
# → stage mirrors prod data at https://stage.leaguesphere.app

# Isolated copy on the test box:
./servyy-test.sh --tags ls.db.sync
# → stage stack on servyy-test.lxd now holds a prod-data clone (nothing public exposed)
```

The stage **stack must already exist** on the target host (its `leaguesphere_stage.mysql`
container is the import target). Deploying the stack runs the sync for you, so a clean first
run on the test box is:

```bash
./servyy-test.sh --tags ls.app.stage   # deploys stage stack on servyy-test + runs ls.db.sync
./servyy-test.sh --tags ls.db.sync     # later: just re-pull fresh prod data
```

`ls.db.sync` also runs automatically as part of any `ls.app.stage` / `ls.app` deploy.

> **Destructive on the target stage DB:** step 3 wipes that host's staging DB every run. That's
> intended — stage is a disposable mirror of prod. Prod is read-only here (dump only); nothing
> is written back.

---

## Logs & metrics

All container logs flow **stdout/stderr → Promtail → Loki**, explorable in Grafana.

- **Grafana:** https://monitor.lehel.xyz — dashboard **"leaguesphere"** (Traefik/Prometheus
  metrics: request rate, 5xx error rate, p50/p95 response time).
- **Loki datasource** inside Grafana is `loki` (`http://loki:3100`); Prometheus is `prometheus`.
- **Loki `container` labels** to query (use `query_range`, and the **container** name, not the
  compose-service name):

  | Environment | Backend | Web |
  |---|---|---|
  | Prod | `leaguesphere.app` | `leaguesphere.www` |
  | Stage | `leaguesphere_stage.staging-app` | `leaguesphere_stage.www` |
  | Demo | `leaguesphere-demo.demo-app` | `leaguesphere-demo.www` |

Example LogQL (last hour of prod backend errors):
```logql
{job="docker", container="leaguesphere.app"} | json | level=~"ERROR|CRITICAL"
```

Quick log access without Grafana:
```bash
ssh lehel.xyz "docker logs leaguesphere.app --tail 100 -f"            # prod backend
ssh lehel.xyz "docker logs leaguesphere_stage.staging-app --tail 100" # stage backend
```

See the repo `CLAUDE.md` › "Testing Loki Queries" for the raw `curl`/`X-Scope-OrgID` recipe.

---

## Quick reference card

```text
PROD    leaguesphere.app          host lehel.xyz   db s207.goserver.host (external)
        containers: leaguesphere.app / leaguesphere.www
        deploy:  ./servyy.sh --tags ls.app.prod --limit lehel.xyz
        logs:    docker logs leaguesphere.app   | Grafana "leaguesphere"

STAGE   stage.leaguesphere.app    host lehel.xyz   db leaguesphere_stage.mysql (container)
        containers: leaguesphere_stage.staging-app / .www / .mysql
        deploy:  ./servyy.sh --tags ls.app.stage --limit lehel.xyz
        prod-data clone: ./servyy.sh --tags ls.db.sync --limit lehel.xyz

DEMO    demo.leaguesphere.app     host lehel.xyz   resets nightly
        deploy:  ./servyy.sh --tags ls.demo --limit lehel.xyz

TEST    servyy-test.lxd           two modes:
        (a) pytest DB — bare MariaDB `mysql`, synthetic fixtures
            setup:   ./container/spinup_test_db.sh --fresh   (from leaguesphere repo)
        (b) prod-data repro — deploy STAGE stack here + sync prod data
            setup:   ./servyy-test.sh --tags ls.app.stage     (then ls.db.sync to refresh)
```
