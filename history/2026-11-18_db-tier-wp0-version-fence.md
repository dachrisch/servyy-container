# DB tier WP-0 — fence the database versions

Date: 2026-11-18
Plan: `docs/plans/2026-11-17_db-tier-topology.md` (Phase 0), work package
`docs/plans/2026-11-18_db-tier-work-packages.md` (WP-0).
Branch: `db-tier/wp0-version-fence`.

**Goal.** No floating database tags and no unattended database minor/major upgrades anywhere;
patch delivery becomes a scheduled `db` watchtower scope, and a mixed version line becomes a
pre-deploy failure instead of a convention.

## What changed and why

### 1. Tags pin the minor and float the patch (D1)

| File | Before | After |
|---|---|---|
| `photoprism/docker-compose.yml` | `mariadb:lts` | `mariadb:12.3` |
| `shared/docker-compose.yml` (`shared.mongo`) | `mongo:9.0.8` | `mongo:9.0` |
| `moodle/docker-compose.yml`, `bnb-office/docker-compose.yml` | `mariadb:12.3` | unchanged |
| `shared/docker-compose.yml` (`shared.db`) | `postgres:15` | unchanged |

`lts` is banned with `latest`: both re-point across minors without a PR (`lts` had already
carried 13.0.2 to another host's fleet — the same alias that put 13.0.2 on LS prod). An exact
patch pin is equally wrong in the other direction: watchtower can only deliver a patch if the
tag is re-pointed on release, so `mongo:9.0.8` could never receive a fix.

Both replacement tags resolve to exactly the digest that was already running, so neither
change is a version change today (`mariadb:12.3` and `mariadb:lts` both → `sha256:4ebbcf…`;
`mongo:9.0` and `mongo:9.0.8` both → `sha256:b0c835…`, verified against the registry and
`servy`). They are fences, not upgrades.

### 2. A `db` watchtower scope (D15)

`portainer/docker-compose.yml` gains `watchtower-db` next to `-prod`/`-dev`:
`WATCHTOWER_SCOPE=db`, `WATCHTOWER_SCHEDULE="0 0 6 * * *"` (one fixed daily slot, deliberately
**not** `WATCHTOWER_POLL_INTERVAL`), `WATCHTOWER_CLEANUP`, `WATCHTOWER_INCLUDE_RESTARTING`,
`WATCHTOWER_HEALTH_CHECK_GATED`, `WATCHTOWER_HEALTH_CHECK_TIMEOUT=2m`,
`WATCHTOWER_WARN_ON_HEAD_FAILURE=never`, `WATCHTOWER_COMPOSE_DEPENDS_ON`, `traefik.enable=false`,
`restart: unless-stopped`, and `com.centurylinklabs.watchtower.scope=db` on the instance itself.

06:00 is the only window that fits between the hourly dumps (:30/:40/:50), restic
02:00–04:00 and the Firefly import at 05:00; a poll interval would eventually drift into a
dump. A database patch is a same-line image refresh, the fork rolls back when the replacement
never reports healthy, and the tag names the minor — so an unattended pull cannot cross a line
(D1/D15). Minors stay a reviewed Renovate PR.

Every database server moved to that scope (a label change recreates the container):

| Container | Label before | Label after | Source |
|---|---|---|---|
| `shared.mongo` | `=prod` | `=db` | `shared/docker-compose.yml` |
| `shared.db` (postgres) | `=prod` | `=db` | `shared/docker-compose.yml` |
| `photoprism.mariadb` | `=prod` | `=db` | `photoprism/docker-compose.yml` |
| `moodle.db` | none | `=db` | `moodle/docker-compose.yml` |
| `bnb-office.db` | none | `=db` | `bnb-office/docker-compose.yml` |
| `leaguesphere.db` | `=prod` | **not touched here** | leaguesphere repo's `deployed/docker-compose.yaml` (other repo, WP-0's PR there) |

`shared.redis` (cache, not a database of record) keeps `=prod`; every other `=prod` label in
the repo belongs to an app, not a database server.

### 3. `MARIADB_AUTO_UPGRADE=1` on the high tier

`ansible/plays/roles/ls_app/templates/ls.env.j2` gains `MARIADB_AUTO_UPGRADE=1`. LS prod never
had it; with patches landing unattended the entrypoint must run `mariadb-upgrade` on every
start so `mysql.*` stays on the new binary. The template lives in this repo, so no second
change is needed in the leaguesphere repo for this item. `leaguesphere.db` reads `ls.env` via
`env_file:`, so the next LS deploy recreates that container (~1–2 min, no data change, and
`mariadb-upgrade` is a no-op on the already-13.0.2 datadir).

### 4. Renovate fence

`renovate.json` keeps the global "automerge non-major" rule and adds two rules after it (later
rules win):

- `mariadb`, `mongo`, `postgres` + `patch` → `enabled: false`. Watchtower owns patches, and
  Renovate must never rewrite `mariadb:13.0` into a concrete `13.0.3` (which would fence the
  server off from future fixes).
- the same packages + `minor`/`major` → `automerge: false`,
  `dependencyDashboardApproval: true`, `groupName: "database minor/major"`, so a hop is one
  reviewed, approved change (Phase 10).

### 5. Drift guard (D8)

**`ansible/plays/tasks/db_version_guard.yml`** — included as the first `pre_task`, tagged
`always`, from **both** `plays/user.yml` (the docker play) and `plays/leaguesphere.yml` (after
its enablement guard): `leaguesphere.yml` applies the high tier's tag on its own, so a
`--tags ls.app` run would otherwise restart prod's database with no check at all — exactly the
ordering Phase 10 depends on.

- Intended tags are read from the **controller** checkout (`docker.local_dir`), not the host's:
  `pre_tasks` run before the repo clone role, so the host copy is the *previous* commit.
  Deploys are merge-before-deploy, so the controller is at origin/master — the commit the
  clone fetches.
- Static server list for Phase 0 (`db_tenants.yml` replaces it in WP-3): `leaguesphere.db`
  (mariadb, high), `shared.mongo` (mongo), `shared.db` (postgres), and `photoprism.mariadb`,
  `moodle.db`, `bnb-office.db` as `retiring: true`.
- Rules per engine, over the servers **present on this host**: a differing minor among active
  servers **fails** the play before any service task; a `retiring` server whose tag is not
  `mariadb:12.3` **fails** (D14); a server whose tag carries no minor (`latest`/`lts`) is
  warned about and excluded, never guessed at. Absent containers are a skip (codey has none).
- Failure messages name every server of the engine with its observed tag and point at
  `leaguesphere/deployed/docker-compose.yaml` when `leaguesphere.db` is involved.
- Override for Phase 10 hop runs only (D8): `-e db_version_guard_allow_drift=<engine>`
  downgrades the minor-line check for that engine to a warning; it never downgrades the
  `retiring` check.

**`ansible/plays/tasks/db_version_drift_push.yml`** — a `post_task` of the same play. It
compares the running image ID (`docker inspect --format '{{.Image}}'`) across the active
servers of each engine, warns when they differ and pushes `db_version_drift{engine}` per
engine — `1` if they differ, else `0` — with the **existing** probe mechanism copied from
`roles/system_probe`: `PUT http://localhost:9091/metrics/job/system_db_version`, no auth,
gated on the same "host runs the monitor stack" condition. It can never fail a run: a
watchtower pull legitimately leaves the fleet split for a few hours.

Both task files are pulled in with **`import_tasks`**, not `include_tasks`: a dynamic include
inherits its `tags: [always]` only on the include statement, so under any `--tags` filter
(`user.docker.shared`, `ls.app`, …) the include would run and every untagged task inside it
would be **skipped** — the guard and the drift push would be silent no-ops exactly where D8
promises they always run. A static import applies `always` to each task in the file (measured
on ansible-core 2.20.1: include → child skipped, import → child ran, `--list-tasks` shows the
children only with the import). The same gotcha is why `roles/restic/tasks/main.yml` uses
`include_tasks` + `apply.tags` for `seed_guard.yml`. Verified after the change:
`--tags user.docker.monitor`, `--tags user.docker` and a full run each list all 12 guard and
all 8 drift tasks once, `--tags ls.app` lists all 12 guard tasks.

`monitor/provisioning/alerting/alert-rules.yml` gains `db_version_drift > 0` for **24 h**
(medium, `infrastructure-alerts`): long enough to ignore a healthy in-flight patch, short
enough to catch a pull that never reached every server.

**Documented deviation (from the plan text, not from the work package).** For
`leaguesphere.db` the intended tag is **unknown**, and its RUNNING tag is compared instead.
Its compose file lives in the leaguesphere repo, which this play only pulls later
(`ls_app` → `git pull`), so the file that will be applied does not exist at pre-check time;
reading the host copy would read the previous commit and could fail a *good* deploy (going
from `mariadb:latest` to `mariadb:13.0`, the stale copy still says `latest`). Today that
running tag is `mariadb:latest`, so the guard warns "cannot verify" and excludes it — the
high tier joins the equality check as soon as the leaguesphere PR lands. With only one active
MariaDB server in the Phase-0 list, the minor-line check is therefore **dormant** until a
second active server exists (WP-4/5/6); what it enforces today is D14 on the three retiring
servers, and it becomes the real fleet gate as the tiers appear.

## Containers this deploy recreates (one restart each, no data movement)

| Host | Container | Cause | Image |
|---|---|---|---|
| servy (prod) | `portainer.watchtower-db` | new instance (created) | `openserbia/watchtower:latest` |
| servy (prod) | `shared.mongo` | tag 9.0.8 → 9.0, label prod → db | same digest (pulled, `9.0` was not in the local store) |
| servy (prod) | `shared.db` | label prod → db | unchanged |
| servy (prod) | `moodle.db` | new label | local `mariadb:12.3` (12.3.3), no pull |
| servy (prod) | `bnb-office.db` | new label | local `mariadb:12.3` (12.3.3), no pull |
| servy (prod) | `photoprism.mariadb` | tag lts → 12.3, label prod → db | **see the pre-pull note below** |
| servy (prod) | `leaguesphere.db` | `ls.env` gains `MARIADB_AUTO_UPGRADE=1` (next LS deploy) | unchanged (`mariadb:latest` → 13.0.2; the leaguesphere PR pins it) |
| servyy-test | `shared.mongo`, `moodle.db`, `bnb-office.db` | labels | local images |
| codey | — | no database container, no `portainer` service | — |

Order: stagger them (WP-0 says one server at a time), and deploy `shared.mongo` **after**
WP-1 is merged (it is: `9552f2a`..`9ed1aac` on master), because recreating it was the hazard
WP-1's `fail`-instead-of-wipe removed.

**Pre-pull note for `photoprism.mariadb`:** prod's local `mariadb:12.3` tag is the older
12.3.x build (`sha256:d46e102…`) while `mariadb:lts` is the current one
(`sha256:4ebbcf…`). `docker_service` uses compose's `missing` pull policy, so switching the
tag without a pull would recreate PhotoPrism on the *older* patch. Run
`docker pull mariadb:12.3` on servy first (or let the `db` scope pull it at 06:00 and restart
again) — both patches are inside 12.3, so system tables are identical and either order is safe.

## Verification (static — no host was deployed to)

All commands exit 0 unless stated.

| Command | Result |
|---|---|
| `docker manifest inspect mariadb:12.3 / mariadb:13.0 / mongo:9.0 / postgres:15` (on servy) | all `EXISTS`; cross-checked against the Docker Hub tag API (`mariadb:12.3` `sha256:4ebbcf1…`, `mariadb:lts` the same digest, `mongo:9.0` `sha256:b0c835c…` = the running `9.0.8`, `postgres:15` `sha256:2663a9f…` = the running digest) |
| `ansible-playbook plays/user.yml --syntax-check -i production` | pass |
| `ansible-playbook plays/leaguesphere.yml --syntax-check -i production` | pass |
| `ansible-playbook servyy.yml --syntax-check -i testing` | pass |
| `yamllint -c ../.yamllint.yml` (the 5 compose files, both new task files, both plays, `ls.env.j2`) | 0 new findings. `ls.env.j2` **errors** as YAML (`expected '<document start>'`) and `moodle`/`photoprism` compose carry 3 line-length/comment/blank-line warnings — all byte-identical to `master` (checked against `git show master:…`), i.e. pre-existing and untouched by this change |
| `python3 -m json.tool renovate.json` | pass |
| `ansible-lint plays/tasks/db_version_guard.yml plays/tasks/db_version_drift_push.yml plays/user.yml plays/leaguesphere.yml` | pass, production profile |
| 24 assertions over the 5 changed compose files (parsed with PyYAML): images, every `scope=db` label, `shared.redis` still `=prod`, `watchtower-db` env/labels/restart, peers intact | 24/24 pass |

**Guard logic, evaluated offline** (localhost, a `docker inspect` shim fed from a JSON fixture,
the two real task files included by a test play — no host contacted):

| Case | Fixture | Result |
|---|---|---|
| all equal | `leaguesphere.db`=`mariadb:13.0`, `shared.mongo`=`mongo:9.0`, `shared.db`=`postgres:15`, three servers on `mariadb:12.3` | **pass**; list printed with the tag read from each compose file |
| today's real tags | `leaguesphere.db`=`mariadb:latest`, `photoprism.mariadb` running `lts` with `12.3` in compose, `mongo` running `9.0.8` with `9.0` in compose | **pass**; warns "cannot verify leaguesphere.db — tag names no minor", excluded; **uses the compose tag, not the running one** for photoprism/mongo (`12.3`, `9.0`) |
| minor mismatch | same fixtures, two active MariaDB servers on `13.0` vs `12.3` (the three `retiring` flags temporarily flipped so a second *active* server exists) | **fail**, exit 2: "Refusing to deploy: mariadb servers are on different minor lines — leaguesphere.db (mariadb:13.0), photoprism.mariadb (mariadb:12.3) … point at leaguesphere/deployed/docker-compose.yaml" |
| same mismatch + `-e db_version_guard_allow_drift=mariadb` | as above | **pass**, with the "DOWNGRADED to a warning" notice |
| retiring off its line | `photoprism/docker-compose.yml` set to `mariadb:13.0` | **fail**, exit 2: "photoprism.mariadb (mariadb:13.0) is `retiring: true` (D14) and must stay on mariadb:12.3 … fix photoprism/docker-compose.yml" |
| container absent | empty fixture (codey-like) | **pass**: "no listed database container runs on this host. Absent here: …" |
| patch drift | two active servers on the same tag, different image IDs, monitor enabled, fake Pushgateway | **pass** (never fatal), warns, `PUT /metrics/job/system_db_version` with `db_version_drift{engine="mariadb"} 1`, `mongo 0`, `postgres 0` — real newlines, valid exposition format |
| no drift | all image IDs equal | **pass**, payload `mariadb 0`, `mongo 0`, `postgres 0` |
| real checkout | `docker.local_dir` = this repo | **pass** — the changed compose files parse and yield `mariadb:12.3`, `mongo:9.0`, `postgres:15` |

## Rollback

Revert this commit (one commit, no secrets, no data touched):

- tags go back to `mariadb:lts` / `mongo:9.0.8`; the labels go back to `=prod` (or none),
  which recreates the same containers back onto the images they run today;
- `watchtower-db` is removed (declared, so `docker compose up` removes it; the container can
  be `docker rm`-ed if compose leaves it);
- Renovate automerges database patches again, and the guard/drift push disappears.

No datadir is opened by anything new, no volume is created or removed, and no secret is
involved. Reverting `ls.env.j2` recreates `leaguesphere.db` once more on the next LS deploy.

## Not done here (by design)

- `leaguesphere.db`'s tag (`mariadb:latest` → `mariadb:13.0`) and its `=db` label ride the
  **leaguesphere** repo's PR; `leaguesphere_stage.mysql` / `leaguesphere-demo.mysql` are not in
  the Phase-0 server list (they are `db_tenants.yml` rows in WP-3).
- Deploy, the test-host-first verification and the exit-gate measurements (one watchtower per
  scope, Renovate dashboard, a forced `mariadb:13.1` run) happen after the merge, per the
  merge-before-deploy rule.

---

## WP-0e — the three open drills (2026-11-19)

WP-0 shipped and its three environments run the fence (prod 2026-11-18, stage + demo
2026-11-19). Three exit-gate items were still unproven at play level. Nothing below changed
production: no deploy, no container restart, no image pull.

### Drill 1 — a real play-level minor-mismatch failure (prod, read-only) — PASSED

On a throwaway branch, `photoprism.mariadb` (its compose really says `mariadb:12.3`) was
flipped to `retiring: false`, which puts it into the D8 equality set next to
`leaguesphere.db` (`mariadb:13.0`). Then, on prod:

```
ansible-playbook plays/user.yml -i production --limit servy.lehel.xyz --tags user.docker.monitor
```

aborted in the guard's first pre_task, exit 2, `ok=12 changed=0 failed=1` (nothing applied):

```
TASK [Fail when active database servers of one engine are on different minor lines (D8)]
[ERROR]: Task failed: Action failed: Refusing to deploy: mariadb servers are on different
minor lines — leaguesphere.db (mariadb:13.0), photoprism.mariadb (mariadb:12.3).
The tag names the minor (D1), so a server can only change line through a reviewed PR,
one tier per run (Phase 10, then the leaguesphere high tier last): patch the odd one out's
compose tag before deploying, or pass -e db_version_guard_allow_drift=mariadb for a hop run.
leaguesphere.db is one of them: its tag lives in leaguesphere/deployed/docker-compose.yaml
(other repo).
```

The override was then proven on the same branch and host with the guard run alone (the
production task file imported by a minimal play, so no service task and no post-task can run):

```
ansible-playbook -i production /tmp/…/drill1-guard-only.yml -e db_version_guard_allow_drift=mariadb
→ exit 0, and:
"db_version_guard_allow_drift is set for mariadb: the minor-line equality check is DOWNGRADED
 to a warning for that engine. This is correct only for a Phase 10 hop run …"
TASK [Fail when active database servers …] skipping (mariadb)
```

Side effects: none — `changed=0`; `monitor.grafana/prometheus/loki` kept their timestamps;
`db_version_drift` stayed `0/0/0` (the play aborts before post_tasks, so the drift push never
ran and could not have published a synthetic `mariadb 1`).

**Finding while running it: the guard is blind under `--check`.** The prescribed
`… --check` run exits **0** and proves nothing: `Inspect each listed database container` is
skipped (the `command` module does not support check mode), so every server resolves with an
empty tag — the log shows `leaguesphere.db ()` and D8 skipping. A `--check` run that "passes"
must not be read as a version check. Follow-up (not WP-0): give that task `check_mode: false`
(it only reads) so `--check` runs are honest.

### Drill 2 — the drift alert exists where Grafana reads it — PASSED

- Pushgateway: `db_version_drift{engine="mariadb"} 0`, `{engine="mongo"} 0`,
  `{engine="postgres"} 0`.
- The provisioned file on the host is byte-identical to master's
  (`md5 c50b73cc47b287618d52e22b3c531332` for both
  `monitor/provisioning/alerting/alert-rules.yml`).
- Grafana, asked over its API (admin credential read from the rendered `monitor/grafana.env`
  on the host and used in-process — never printed), reports the rule as loaded and enabled:
  `uid: db_version_drift`, title **Database Patch Drift**, folder `Infrastructure`, group
  `infrastructure-alerts` (interval 1m), `for: 1d` (= 24 h), `labels.severity: medium`,
  `is_paused: false`, `condition: C`, `noDataState: OK`, `execErrState: Error`,
  expr `db_version_drift > 0`, with the summary/description annotations intact.
- A query through the rule's own datasource (`/api/datasources/proxy/uid/prometheus/…?query=
  db_version_drift`) returns the three series with value `0`, i.e. the alert can evaluate it.

A *real* digest mismatch is not producible yet: it needs two **active** servers of one engine,
and the only active MariaDB server is `leaguesphere.db` (the 12.3 servers are `retiring`).
That arrives with WP-4.

### Drill 3 — watchtower health-gate rollback — DEFERRED (no safe host)

Verified on every host:

| host | watchtower instances | containers labelled `scope=db` |
|---|---|---|
| servy (prod) | `watchtower-db` (db), `-prod`, `-dev` | `leaguesphere.db`, `shared.mongo`, `shared.db`, `photoprism.mariadb`, `moodle.db`, `bnb-office.db` (+ the watchtower itself) |
| servyy-test | **none at all** | `shared.mongo`, `moodle.db`, `bnb-office.db` |
| codey | `watchtower-prod`, `watchtower-dev` (no `-db`; its portainer project predates WP-0) | none |

There is exactly **one** db-scope watchtower in the fleet and it lives on production, where a
deliberately broken database image is not an acceptable test (it would restart a real database
and, if the gate failed, keep it on a broken image). servyy-test has the containers but no
db-scope watcher to act on them, and codey has neither. **No improvised variant was run.**

Unblocked by WP-4: the `db-nonprod` tier on servyy-test should carry its own
`watchtower` instance for that tier's scope, at which point a broken-image drill is a
non-prod test with a disposable datadir. Until then the health gate remains proven only by
the fork's own behaviour and by the images it already rolled back before WP-0
(history/2026-11-03_shared-mongo9-kernel7.md).

Incidental observation: after WP-0 the three servyy-test database containers carry
`scope=db` while no db-scope watcher exists there. Harmless today (nothing looks at that
scope on that host) and it disappears by itself when the test host gets its own tier watcher,
but it means "labelled" ≠ "patched" on test.

---

## WP-4b — cutover incident and the two fixes (2026-11-18)

The WP-4 cutover (stage + demo onto `db-nonprod.mariadb`) got the **apps** across — both
stacks recreated against the tier, `MYSQL_HOST=db-nonprod.mariadb`, DB-backed pages 200 —
and then stopped on two repo bugs, before the supporting plumbing was deployed.

### Deviation: stage's old server was REMOVED, not stopped

`ls_app`'s compose task ran with `remove_orphans: true`, and stage's `mysql:` service had
just been dropped from `deployed/docker-compose.staging.yaml`. Compose therefore **deleted**
`leaguesphere_stage.mysql` during the deploy — the plan requires a cutover to *stop* the old
server and keep it as the one-week rollback. Demo was spared because the `ls_demo` role has
no orphan removal.

The data is intact: `…/container-stage/deployed/mysql-data` (the compose `./mysql-data` bind
mount) is untouched, as is `…/container-demo/deployed/mysql-data`. So the rollbacks differ:

- **stage** — `docker start` is not available (no container). Rollback = revert the two
  merges (this repo + `e58942ccc`), restore `MYSQL_HOST`, and redeploy stage, which
  recreates the `mysql:` service on that datadir.
- **demo** — `leaguesphere-demo.mysql` is still **running**; the rollback is `docker start`
  (if stopped) plus reverting the compose, or simply reverting the compose and redeploying.

**Fix so the next cutover cannot repeat it:** `ls_app`'s compose task now takes
`app_compose_remove_orphans` (default `true`), and the stage invocation in
`plays/leaguesphere.yml` sets it to **`false`** with a comment naming the rollback container.
`ls_runs_own_db` was also corrected: only `leaguesphere` (high tier) still runs its own
database, so the seven DB-only tasks skip for stage instead of failing at
`Wait for MySQL to be ready` (`container: null`).

### Second fix: the grant-host assert

The widened private-range check `^(172\.(1[6-9]|2[0-9]|3[01])|192\.168)\.[0-9]+\.%$` demanded
four octets after `172.16/12`, so prod's three-octet `172.25.%` no longer matched and the
leaguesphere play aborted with the role's own "re-verify which containers share that network"
message. Correct form, verified against an 11-case matrix:
`^(172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.[0-9]+\.)%$`. The derivation in `discover.yml` was
also prefix-corrected — it took two octets unconditionally, which turned the tier's
`192.168.16.0/20` into the /16-wide `192.168.%`; it now takes `ceil(prefix/8)` octets
(`172.25.%` for a /16, `192.168.16.%` for the /20).

### Still open after these fixes

Deploy the plumbing (`dba.env` re-pointed at the tier, `ls_stage_access_admin`, the reaper,
the nightly script), stop `leaguesphere-demo.mysql`, run the nightly sync once by hand to
prove the retarget, then the guard/drift checks. Until then stage's `db-access` sidecar is
running with the old `dba.env` (`DBACCESS_HOST=mysql`) and logs
`ERROR 2005 (HY000): Unknown server host 'mysql'` — off the app's request path, so the site
is unaffected.
