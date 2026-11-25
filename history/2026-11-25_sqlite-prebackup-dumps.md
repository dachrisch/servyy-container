# 2026-11-25 — SQLite pre-backup dumps (RPO match for DR restore)

Status: deployed to production (servy + codey), verified. Docs-only follow-up to
GitHub PR #373 (merged to `master`) and its mirror on the Forgejo
`claude/dr-secrets-redesign` branch (`9230e6ec`).

## Problem

The DR review of 2026-11-25 found a restore-consistency gap:

- Forgejo bare repos and service files are in the hourly `restic-home` snapshot,
  but the two critical SQLite databases were only covered by **nightly** dumps
  (`forgejo dump` for `ci/data/data/gitea.db`; the Vaultwarden dump timer for
  `pass/vw-data/db.sqlite3`).
- Restoring a snapshot therefore paired a ~1 h-old file/repo tree with a DB that
  could be up to 24 h older. A repo created after the last nightly dump exists
  on disk but is missing from the restored DB — rehearsal pass 1 hit exactly
  this ("Repository not found" on HTTP clone) and needed an ad-hoc reconcile.
- Hourly snapshots also capture live SQLite files with `-wal`/`-shm`, which are
  potentially torn and must be discarded on restore.

Accepted fix: take a consistent `.backup` of both live DBs **immediately before
each hourly restic-home run**, inside `restic-home`'s source path, so every
snapshot contains a DB copy from (effectively) the same instant as the files.

## Solution (PR #373)

- New role `ansible/plays/roles/sqlite_prebackup_dump/` renders and runs
  `~/.vaultwarden-dump/sqlite-prebackup-dumps.sh` from the **home-scope**
  `restic_backup.sh.j2` hook, before restic starts.
- Forgejo: `ci/data/data/gitea.db` → `ci/data/backup/gitea-db-*.sqlite3`.
- Vaultwarden: `pass/vw-data/db.sqlite3` → `pass/backup/vaultwarden-db-*.sqlite3`
  (`pass/backup` is deploy-user-owned; `pass/vw-data` is root-owned by the
  container, so the dump dir was moved there during pass 2).
- Keeps the last 3 dumps per DB; pushes `dr_prebackup_dump_failure{db=…}` (0/1)
  and `dr_prebackup_dump_age_seconds{db=…}` plus per-run `push_time_seconds` to
  the local Pushgateway under job `db_prebackup_dumps`. The hook deliberately
  never fails restic: the files are still snapshotted, but the failure metric
  pages so a mismatched restore cannot go unnoticed.
- Grafana rules in `monitor/provisioning/alerting/alert-rules.yml`:
  - `dr_prebackup_dump_failure` ("Pre-backup SQLite Dump Failed",
    `noDataState: OK`) — `dr_prebackup_dump_failure > 0` for 5 m.
  - `dr_prebackup_dump_stale` ("SQLite Pre-backup Dump Hook Stale",
    `noDataState: Alerting`) — stale/absent `push_time_seconds{job="db_prebackup_dumps"}`
    beyond 7200 s (two missed hourly runs), also fires when the series never
    existed.
- Both Molecule scenarios (`default`, `prebackup`) verify the dumps and metrics.

## Files

- `ansible/plays/roles/sqlite_prebackup_dump/` (new role: tasks, defaults, meta,
  service/timer + script templates, two Molecule scenarios).
- `ansible/plays/roles/restic/templates/restic_backup.sh.j2` — call the hook on
  home-scope runs.
- `ansible/plays/roles/user/templates/restic_backup.sh.j2` — related template.
- `monitor/provisioning/alerting/alert-rules.yml` — the two rules above.
- Docs/runbook mirror on the Forgejo DR branch (`9230e6ec`).

## Deploy results

- **servy** (from `master`):
  `./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,restic.backup,user.docker.sqlite.prebackup`
  — succeeded; the legacy standalone vaultwarden-dump units were removed.
- Natural `restic-home` run at **20:03:48 CET** (2026-11-25) ran the hook:
  - wrote `gitea-db-20261125-200349.sqlite3` and
    `vaultwarden-db-20261125-200349.sqlite3`;
  - `PRAGMA integrity_check` = `ok` on both;
  - Pushgateway job `db_prebackup_dumps`: `failure=0` for both with a fresh
    `push_time_seconds`;
  - log: `Pre-backup SQLite dumps complete` then `Backup completed successfully`
    at 20:03:58.
- **Snapshot proof:** latest `home` snapshot `abcc25b6` at
  `2026-11-25T20:03:53.967+01:00` contains both dump files:
  `ci/data/backup/gitea-db-20261125-200349.sqlite3` and
  `pass/backup/vaultwarden-db-20261125-200349.sqlite3`.
- **codey** (alert rules), from `master` after `git pull`:
  `./servyy.sh --limit codey.lehel.xyz --tags user.repo.clone,user.docker.monitor`
  — `ok=195 changed=4 unreachable=0 failed=0 skipped=47`.
  Both rules provisioned (86 rules total) and in non-firing (`inactive`, the
  Grafana unified-alerting healthy state); the
  `push_time_seconds{job="db_prebackup_dumps"}` series is present and fresh
  (`2026-11-25 19:03:53 UTC` = 20:03:53 CET, ~24 min old at check time vs the
  7200 s threshold). Checkout is on `master`; the `monitor_grafana_auth` check
  passed with the re-assert task skipped, i.e. **no admin password drift**.

## Verification commands

Snapshot contents (on servy; `env.home` sourced in a sudo subshell, values never
printed):

```bash
ssh servy.lehel.xyz "sudo bash -s <<'EOS'
set -a; . /etc/restic/env.home; set +a
restic snapshots --tag home --latest 1 --json | jq -r '.[] | \"id=\"+.short_id+\" time=\"+.time'
snap=\$(restic snapshots --tag home --latest 1 --json | jq -r '.[0].short_id')
restic ls \"\$snap\" | grep -E 'gitea-db-20261125-200349|vaultwarden-db-20261125-200349'
EOS"
```

Dump integrity on a read-only mount (SQLite needs to write beside the file, so
open immutable as the container user):

```bash
docker exec -u 1000:1000 ci.forgejo sh -c \
  'sqlite3 "file:/data/backup/gitea-db-20261125-200349.sqlite3?immutable=1" "PRAGMA integrity_check;"'
ssh servy.lehel.xyz 'sudo -u cda sqlite3 "file:/home/cda/servyy-container/pass/backup/vaultwarden-db-20261125-200349.sqlite3?immutable=1" "PRAGMA integrity_check;"'
```

Grafana rule state and the dependency series (password stays inside the
container):

```bash
ssh codey.lehel.xyz "docker exec monitor.grafana sh -c 'curl -s -u \"\${GF_SECURITY_ADMIN_USER:-admin}:\$GF_SECURITY_ADMIN_PASSWORD\" http://localhost:3000/api/v1/provisioning/alert-rules'" \
  | jq -r '.[] | select(.uid|test("dr_prebackup_dump")) | [.uid,.title,.noDataState]|@tsv'
ssh codey.lehel.xyz "docker exec monitor.grafana sh -c 'curl -s -u \"\${GF_SECURITY_ADMIN_USER:-admin}:\$GF_SECURITY_ADMIN_PASSWORD\" http://localhost:3000/api/prometheus/grafana/api/v1/rules'" \
  | jq -r '[.data.groups[].rules[]|select(.uid|test("dr_prebackup_dump"))|.state]'
```

## Follow-up

These dumps are the DB half of the DR restore path. Rehearsal pass 3 uses the
newest `.backup` files from a snapshot, deletes their `-wal`/`-shm`, and
measures each DB's age against the snapshot time (must be minutes, not hours).
