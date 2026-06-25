# Decouple LeagueSphere DB Stand-up From the Running App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make standing up the prod local-MariaDB container non-disruptive to the running app — deploying adds only the `db` container; `app`/`www` are not recreated — and split the cutover into a no-maintenance Phase A and a windowed Phase B.

**Architecture:** Revert the leaguesphere prod compose's `app`/network changes back to the exact shape prod runs today, keeping only the additive `db` service on the `backend` network (which `app` already shares, but `app` keeps `MYSQL_HOST=external` so it stays unwired). Validate the "no app recreation" claim on `servyy-test` by container-ID comparison. Update plan/docs to the two-phase cutover. The network rename (`database`→`egress`) and the `db_host` flip are deferred to Phase B (cutover), where the app is recreated once anyway.

**Tech Stack:** Docker Compose (`leaguesphere/deployed/`), Ansible (`container/ansible`), MariaDB.

## Global Constraints

- **Two repos, scoped commands only.** `git -C container …` / `git -C leaguesphere …`; non-git: `cd container && …` / `cd leaguesphere && …`. Never mix a commit across repos.
- **Test-first, no manual prod edits.** Validate on `servyy-test.lxd`. This plan's execution covers code + docs + **test-box** validation only. Prod Phase A and Phase B are run later from the updated runbook **with explicit user approval** — not part of executing this plan.
- **Zero app/www recreation is the success criterion.** Proven by unchanged container IDs across a re-deploy.
- **db stays unwired in this change.** `db` on `backend` (internal: true), no published ports, bind mounts. `app.ls.env` keeps `MYSQL_HOST=external` (`app.db_host` unchanged in `secret_main.yaml`). No `db_host` flip, no network rename here.
- **servyy-test ansible connection (this environment):** the fresh test box authenticates as `ubuntu` with `~/.ssh/id_rsa`, and the agent's ssh-agent holds many keys, so Ansible must be constrained:
  ```
  ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" ANSIBLE_HOST_KEY_CHECKING=False \
  ./servyy-test.sh -u ubuntu <args>
  ```
  Manual ssh: `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd …` (then `sudo docker …`; the `ubuntu` user is not in the docker group).

---

## File Structure

**`leaguesphere` repo:**
- `deployed/docker-compose.yaml` — revert `app.networks` + drop `app.depends_on: db`; restore `database` network; remove `egress` network; keep `db` on `backend`. *(Modify)*

**`container` repo:**
- `docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md` — restructure Task 11 into Phase A / Phase B. *(Modify)*
- `docs/leaguesphere-environments.md` — rewrite the cutover runbook to the two phases. *(Modify)*
- `docs/superpowers/specs/2026-06-24-decouple-db-standup-from-app-design.md` — the design (already committed). *(Reference)*

---

## Task 0: Branches

- [ ] **Step 1: Confirm container branch**

Run: `git -C container rev-parse --abbrev-ref HEAD`
Expected: `feat/decouple-db-standup` (the spec is already committed here).

- [ ] **Step 2: Create the leaguesphere branch**

```bash
git -C leaguesphere checkout -b feat/decouple-db-standup
```
Expected: `Switched to a new branch 'feat/decouple-db-standup'`

---

## Task 1: Revert the prod compose `app`/networks (keep `db` unwired)

**Files:**
- Modify: `leaguesphere/deployed/docker-compose.yaml`

**Interfaces:**
- Produces: a prod compose whose `app`/`www`/networks effective config is identical to the
  pre-migration state (commit `2291cb1d~1`), plus the additive `db` service on `backend`.

- [ ] **Step 1: Capture the pre-migration baseline to diff against**

```bash
git -C leaguesphere show 2291cb1d~1:deployed/docker-compose.yaml > /tmp/ls-compose-premigration.yaml
```
This is the exact `app`/`www`/networks shape prod runs today. The revert must match it.

- [ ] **Step 2: Revert the `app` service networks + remove `depends_on`.** In `deployed/docker-compose.yaml`, the `app` service currently reads:

```yaml
    networks:
      - backend   # For www + db communication
      - egress    # Outbound internet (external APIs etc.) — replaces the egress the removed `database` network provided
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
```
Replace that block with (drop the `depends_on`, restore `database`):

```yaml
    networks:
      - backend   # For www communication
      - database  # For external MySQL access
    restart: unless-stopped
```
(Leave the `app` `healthcheck`, `environment`, `image`, `command`, `labels`, `env_file` untouched — they already match pre-migration.)

- [ ] **Step 3: Restore the `database` network, remove `egress`.** The bottom `networks:` block currently reads:

```yaml
networks:
  backend:
    internal: true
  egress:
    # Non-internal bridge: restores the app's outbound internet access that the
    # removed `database` network (internal: false) used to provide. The `db`
    # service stays isolated on the internal-only `backend` network.
    driver: bridge
  proxy:
    external: true
```
Replace with:

```yaml
networks:
  backend:
    internal: true
  database:
    internal: false  # Allow external connectivity for MySQL
  proxy:
    external: true
```
(Leave `db` on `backend` and `www` on `[backend, proxy]` unchanged.)

- [ ] **Step 4: Validate compose syntax**

Run: `cd leaguesphere/deployed && SERVICE_NAME=x COMPOSE_PROJECT_NAME=leaguesphere SERVICE_HOST=x LOCAL_HOSTNAME=x docker compose -f docker-compose.yaml config -q && echo OK`
Expected: `OK`.

- [ ] **Step 5: Prove `app`/`www`/networks now match pre-migration (no app recreation on prod).** Compare the resolved `app`, `www`, and `networks` config of the reverted file vs the baseline:

```bash
cd leaguesphere/deployed
ENV="SERVICE_NAME=x COMPOSE_PROJECT_NAME=leaguesphere SERVICE_HOST=x LOCAL_HOSTNAME=x"
env $ENV docker compose -f docker-compose.yaml config | yq '.services.app, .services.www, .networks' > /tmp/reverted.app.yaml
env $ENV docker compose -f /tmp/ls-compose-premigration.yaml config 2>/dev/null | yq '.services.app, .services.www, .networks' > /tmp/premig.app.yaml
diff /tmp/premig.app.yaml /tmp/reverted.app.yaml && echo "APP/WWW/NETWORKS MATCH PRE-MIGRATION"
```
Expected: only the `database` network reappears and `egress` is gone; **no diff in `app` or `www`** (the baseline has no `db`, so `networks` differs only by `database` vs `egress` — confirm `app`/`www` blocks are identical). If `app`/`www` differ, find and revert the extra field before continuing.

- [ ] **Step 6: Confirm `db` stays unwired**

Run: `cd leaguesphere/deployed && grep -nE 'ports:|MYSQL_HOST|depends_on' docker-compose.yaml; grep -nE 'db_host' ../../container/ansible/plays/roles/ls_app/vars/secret_main.yaml | head -1`
Expected: no `ports:` anywhere; no `depends_on` on `app`; `secret_main.yaml` `db_host` still external (`s207.goserver.host`).

- [ ] **Step 7: Commit**

```bash
git -C leaguesphere add deployed/docker-compose.yaml
git -C leaguesphere commit -m "fix(prod): keep db unwired — revert app network/depends_on changes

Deploying now only adds the db container; app/www are byte-identical to the
pre-migration shape so Docker does not recreate them. db stays on the internal
backend network with MYSQL_HOST still external. The database->egress rename and
db_host flip move to the cutover window (Phase B)."
```

---

## Task 2: Prove non-disruptive deploy on `servyy-test`

**Files:** none (validation; the test box already runs the leaguesphere stack from earlier work).

**Interfaces:**
- Consumes: reverted compose from Task 1.
- Produces: evidence that deploying the reverted compose to a host already running the
  pre-migration `app` config adds only `db` (unchanged `app`/`www` container IDs).

- [ ] **Step 1: Put the test box into the prod-equivalent baseline.** Deploy the reverted compose once (recreates `app` to the reverted == pre-migration config), then remove `db` to mirror prod's "db not present yet" state:

```bash
cd container/ansible
ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" ANSIBLE_HOST_KEY_CHECKING=False \
./servyy-test.sh -u ubuntu --tags ls.app.prod
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd "sudo docker rm -f leaguesphere.db"
```
Expected: deploy succeeds; `app`/`www` healthy; `leaguesphere.db` removed.

- [ ] **Step 2: Record `app`/`www` container IDs (the "before")**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  "sudo docker inspect -f '{{.Id}}' leaguesphere.app leaguesphere.www" | tee /tmp/ids-before.txt
```
Expected: two container IDs.

- [ ] **Step 3: Deploy the reverted compose again (the action under test)**

```bash
cd container/ansible
ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" ANSIBLE_HOST_KEY_CHECKING=False \
./servyy-test.sh -u ubuntu --tags ls.app.prod > /tmp/ls-redeploy.log 2>&1; echo "EXIT=$?"
```
Expected: `EXIT=0`.

- [ ] **Step 4: Assert app/www NOT recreated, db created**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  "sudo docker inspect -f '{{.Id}}' leaguesphere.app leaguesphere.www" > /tmp/ids-after.txt
diff /tmp/ids-before.txt /tmp/ids-after.txt && echo "APP/WWW UNCHANGED ✅"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  "sudo docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"
```
Expected: `APP/WWW UNCHANGED ✅` (identical IDs) and `leaguesphere.db` → `healthy` (newly created).

- [ ] **Step 5: Confirm the deploy.yaml stop-path stayed dormant**

Run: `grep -E "Stop containers before volume cleanup|state.*stopped" /tmp/ls-redeploy.log | grep -iv skipping; grep -c "changed=" /tmp/ls-redeploy.log`
Expected: no evidence the whole project was stopped (the "Stop containers before volume cleanup" task is skipped). If it shows as `changed`/run, STOP — the destructive path fired and must be addressed before prod.

---

## Task 3: Re-confirm seed + backup under the reverted topology

**Files:** none (validation).

**Interfaces:**
- Consumes: `leaguesphere.db` from Task 2.
- Produces: evidence the seed/backup pipeline is unaffected by the app-network revert.

- [ ] **Step 1: Seed the local db from external and verify rows**

```bash
cd container/ansible
ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" ANSIBLE_HOST_KEY_CHECKING=False \
./servyy-test.sh -u ubuntu --tags ls.db.migrate
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  'sudo docker exec leaguesphere.db bash -c '\''mariadb -h localhost -u root -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"web35_db8\" AND table_type=\"BASE TABLE\";"'\'''
```
Expected: seed completes; base-table count `103` (matches the validated drill baseline). Note: if the test box's `leaguesphere.app` is connected to external and exhausts `max_user_connections`, stop it first (`sudo docker stop leaguesphere.app`) — documented, environmental.

- [ ] **Step 2: Take one mariadb-backup + restic snapshot**

```bash
cd container/ansible
ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" ANSIBLE_HOST_KEY_CHECKING=False \
./servyy-test.sh -u ubuntu --tags restic.backup
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  "systemctl --user start mariadb-backup-ls.service 2>/dev/null; sleep 5; sudo ls /var/jail/home/leaguesphere/container/deployed/mysql-backup/current | head"
```
Expected: `current/` holds the prepared set (`ibdata1`, `mariadb_backup_checkpoints`, the db dir). (Full restore already validated in the destructive drill — `history/2026-06-22_ls-db-restore-drill.md` — no need to repeat here.)

---

## Task 4: Restructure cutover docs into two phases

**Files:**
- Modify: `container/docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md`
- Modify: `container/docs/leaguesphere-environments.md`

**Interfaces:**
- Produces: a runbook where Phase A (db stand-up + seed + backup + restore) carries no
  maintenance-window requirement, and Phase B (cutover) bundles the `database`→`egress` rename
  with the `db_host` flip.

- [ ] **Step 1: Rewrite Task 11 in the migration plan into Phase A / Phase B.** Replace the body of "## Task 11: Production cutover" so it reads as two phases:
  - **Phase A — DB stand-up + validation (no maintenance window, non-disruptive):**
    1. `./servyy.sh --tags ls.app.prod --limit lehel.xyz` — adds `leaguesphere.db` only (app/www untouched).
    2. `./servyy.sh --tags restic.init,restic.backup --limit lehel.xyz`.
    3. `./servyy.sh --tags ls.db.migrate --limit lehel.xyz` — seed; verify parity.
    4. Optional restore drill against the seeded set.
  - **Phase B — cutover (maintenance window, app recreated once, approval-gated):**
    1. Enter maintenance / read-only.
    2. Final delta seed: `./servyy.sh --tags ls.db.migrate --limit lehel.xyz`.
    3. In one deploy: rename `database`→`egress` in `leaguesphere/deployed/docker-compose.yaml` **and** set `app.db_host: leaguesphere.db` in `secret_main.yaml`; `./servyy.sh --tags ls.app.prod --limit lehel.xyz`.
    4. Verify `MYSQL_HOST=leaguesphere.db`; smoke test (login/read/write); exit maintenance.
    5. Set `ls_db_sync_source: "local"` default; commit.
  Add a note: Phase A is safe because the deployed `app`/`www` config is byte-identical to prod, so only `db` is created.

- [ ] **Step 2: Update the cutover runbook in `leaguesphere-environments.md`.** Replace the "Cutover runbook (external → local DB)" section's single sequence with the same Phase A / Phase B split, and add one line under the DB-backup notes: "Standing up `leaguesphere.db` (Phase A) does not touch the live app — the app moves to the local DB only at cutover (Phase B), via the single `db_host` flip + the `database`→`egress` rename."

- [ ] **Step 3: Verify the docs render and reference the right tags**

Run: `grep -nE "Phase A|Phase B|database.*egress|db_host" container/docs/leaguesphere-environments.md container/docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md | head`
Expected: both files show the Phase A/B structure and the rename+flip in Phase B.

- [ ] **Step 4: Commit**

```bash
git -C container add docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md docs/leaguesphere-environments.md
git -C container commit -m "docs: two-phase leaguesphere cutover (non-disruptive db stand-up + windowed flip)"
```

---

## Task 5: Pull requests

**Files:** none (integration).

- [ ] **Step 1: Push both branches**

```bash
git -C leaguesphere push -u origin feat/decouple-db-standup
git -C container push -u origin feat/decouple-db-standup
```

- [ ] **Step 2: Open the leaguesphere PR** (compose revert) against its default branch, body summarizing: keeps db unwired, app/www not recreated, rename+flip deferred to cutover; validated on servyy-test (app/www container IDs unchanged).

- [ ] **Step 3: Open the container PR** (spec + plan + docs) against `master`, referencing the spec and the two-phase runbook.

- [ ] **Step 4: Merge after CI is green** (squash), per the repos' PR convention — with user confirmation.

---

## Self-Review Notes

- **Spec coverage:** compose revert (Task 1) ↔ spec §1; no role-code change + docs-only (Task 4) ↔ spec §2/§3; non-disruptive proof + dormant deploy.yaml (Task 2) ↔ spec §4 + Risks; seed/backup unaffected (Task 3) ↔ spec success criteria.
- **Zero-recreation is tested, not asserted:** Task 2 Step 4 diffs container IDs — the plan fails loudly if the app is recreated.
- **Scope honored:** no `db_host` flip, no network rename, no `deploy.yaml` edit in this plan — all deferred to Phase B / left dormant per the approved spec.
- **Prod is out of execution scope:** only code + docs + test-box validation run here; Phase A/B on prod follow the runbook under explicit approval.
