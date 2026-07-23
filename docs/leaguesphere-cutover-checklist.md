# LeagueSphere — Phase B Cutover Checklist (external → local MariaDB)

> ✅ **EXECUTED 2026-07-08 — cutover complete.** Prod runs on local `leaguesphere.db` (`web35_db8`),
> `RUN_MIGRATIONS=true`. Post-cutover baseline backup taken (restic snapshot `bb4542a9`). Write-up:
> `history/2026-07-08_leaguesphere-phase-b-cutover.md`. Kept below as the as-run record.
> **Deviations:** the final seed was sourced from the stage copy (`leaguesphere_stage`) instead of
> a fresh `s207` pull (§1); the `database`→`egress` net rename (PR #34) was not applied.
> **Remaining:** flip `ls_db_sync_source` default → `local`; decommission `s207` on/after 2026-07-22.

> **One-page, tick-through sheet for cutover day.** Full detail and rationale live in the
> [cutover runbook](leaguesphere-environments.md#cutover-runbook-external--local-db--two-phases).
> This sheet is the *do-it* version: pre-flight → execute → verify → post.
>
> **Plan:** **full-downtime** maintenance window. The app goes fully offline, the final delta
> seed runs against a quiet DB, then a single deploy flips `app.db_host` and brings the app back
> up on the local `leaguesphere.db` container.
>
> **Approval-gated.** Do not start without explicit go-ahead. All deploys run from
> `container/ansible` with `--limit lehel.xyz`.

Host paths used below:
- Prod stack dir on host: `/var/jail/home/leaguesphere/container` (compose project `leaguesphere`)
- Prepared backup set: `…/deployed/mysql-backup/current/`

---

## 0. Pre-flight (recommended — do before announcing the window)

- [ ] **Backups verified healthy** (last checked 2026-06-29; re-run on the day):
  ```bash
  # Timers active & last run recent (:40 dump, :00 restic snapshot)
  ssh lehel.xyz "systemctl --user list-timers --all --no-pager | grep -iE 'mariadb-backup-ls|restic-backup-ls-db'"

  # On-disk set is FRESH and PREPARED (expect: recent mtime, backup_type = log-applied)
  ssh lehel.xyz "sudo stat -c '%y %n' /var/jail/home/leaguesphere/container/deployed/mysql-backup/current && \
                 sudo cat /var/jail/home/leaguesphere/container/deployed/mysql-backup/current/mariadb_backup_checkpoints"

  # Latest restic db snapshot is < 1h old
  ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.db && restic snapshots --tag db --no-lock' | tail -3"
  ```
- [ ] **Restore drill is green** on servyy-test (last pass: 103 → 103 base tables). Re-run if in doubt.
- [ ] **Stop every NON-prod stack still pointed at the external DB** (`web35_8@s207`) — servyy-test,
      any stage-on-external, local dev. Prevents `max_user_connections (1203)` contention during the seed.
      *(With the prod app offline in step 1, the prod pool is gone too — this covers the rest.)*
- [ ] **Confirm the cutover edits are staged** but not yet deployed:
  - `app.db_host` → `leaguesphere.db` in `ansible/plays/roles/ls_app/vars/secret_main.yaml`
  - network `database` → `egress` in `leaguesphere/deployed/docker-compose.yaml`
- [ ] **Announce the maintenance window.**

---

## 1. Execute — full-downtime window

- [ ] **Take the app OFFLINE** (full downtime — no in-flight writes, no DB contention):
  ```bash
  ssh lehel.xyz "cd /var/jail/home/leaguesphere/container && docker compose -p leaguesphere stop app www"
  ```
  *(This is the one intentional manual operational step. The site returns the default error/502
  for the duration — no maintenance page by design.)*

- [ ] **Final delta seed** while the app is down (consistent, no contention):
  ```bash
  cd container/ansible
  ./servyy.sh --tags ls.db.migrate --limit lehel.xyz
  ```
  Verify table parity afterward (base-table baseline = **103**).

- [ ] **Cutover deploy — ONE run** (applies the two staged edits, recreates app/www, brings the
      app back **online on the local DB**):
  ```bash
  cd container/ansible
  ./servyy.sh --syntax-check
  ./servyy.sh --tags ls.app.prod --limit lehel.xyz
  ```

---

## 2. Verify (app is already back up after the deploy)

- [ ] App now points at the local DB:
  ```bash
  ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"   # → leaguesphere.db
  ```
- [ ] DB container healthy:
  ```bash
  ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"  # → healthy
  ```
- [ ] **Smoke test:** login, read a page, perform a write (create/edit), confirm it persists.
- [ ] Logs/metrics clean: `ssh lehel.xyz "docker logs leaguesphere.app --tail 100"` + Grafana
      `https://monitor.lehel.xyz` (dashboard "leaguesphere") — no 5xx spike.
- [ ] **End the maintenance window.**

> ⚠️ **Gotcha — ad-hoc DB access:** the `leaguesphere.db` container inherits
> `MYSQL_HOST=s207…`, so any manual `docker exec leaguesphere.db mariadb …` must pass
> `-h 127.0.0.1` or it chases the dead external host.

---

## 3. Post-cutover

- [ ] Flip the sync default to local and commit:
      set `ls_db_sync_source: "local"` in `ansible/plays/roles/ls_db_sync/defaults/main.yml`.
- [ ] **Record the cutover date.** External DB (`s207.goserver.host`) is retained **14 days** as a
      rollback net → decommission on/after **cutover date + 14 days**.
- [ ] Confirm the next hourly backup of the now-live DB lands in `restic-ls-db`:
  ```bash
  ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.db && restic snapshots --tag db --no-lock' | tail -3"
  ```
- [ ] Update memory / status: Phase B done; mark decommission date.

---

## Rollback (within the 14-day window)

If the cutover must be reversed:

```bash
# 1. Revert app.db_host back to s207.goserver.host in secret_main.yaml
# 2. Redeploy prod app:
cd container/ansible
./servyy.sh --tags ls.app.prod --limit lehel.xyz
ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"   # → s207.goserver.host
```

`leaguesphere.db` can be left running (keeps accumulating backups) or stopped — it does not affect
the rolled-back app. Full detail: [runbook › Rollback](leaguesphere-environments.md#rollback-runbook-local--external-db).
