# Moodle gets real backups: two restic scopes, one drill, three footguns

**Date:** 2026-11-06
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz` and `servyy-test.lxd`
**Relates to:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md)
Task 7, [history/2026-11-04_moodle-moodledata-ingested.md](2026-11-04_moodle-moodledata-ingested.md),
[history/2026-10-08_restic-ls-db-stale-lock-recovery-and-snapshot-monitoring.md](2026-10-08_restic-ls-db-stale-lock-recovery-and-snapshot-monitoring.md)

## Context

Moodle had **no restic coverage at all**. `restic-root` backs up only `/etc` and `/var`, and
`restic-home` explicitly excludes `servyy-container/moodle/data` — the dataroot is `root:root 0750`
with files owned by uid 65534, so the unprivileged home job cannot read it. 5.9 GB of production
content (`moodledata`, 12,538 files) plus a 1.66 GB / 497-table MariaDB lived on a single disk whose
only copies were two manual tarballs written on 2026-11-04.

The hosting plan's Task 7 asked for one scope `restic-moodle` with a `mariadb-backup` prepared set
"including binlogs so a PITR drill is possible". Two facts changed that design during implementation:
`log_bin` is `OFF` on `moodle.db` (so a physical set buys no PITR either), and the DB is a plain
sidecar with no `/backup` bind mount (a physical set would need a compose change).

## Decision

Two independent repos, gated on a new `moodle_enabled` (derived from `services_enabled.moodle`), one
shared password (`restic_password_moodle`, seed file + Vaultwarden item):

| Repo | Source | Timer | Retention |
|---|---|---|---|
| `restic-moodle-db` | `…/data/db-backup/current/` — logical `mariadb-dump --single-transaction --quick --routines --events --triggers --hex-blob --skip-dump-date` \| `gzip -n` | dump `*:40`, snapshot `*:50` | last 24 / hourly 24 / daily 14 / weekly 8 / monthly 6 |
| `restic-moodle-files` | `…/data/moodledata` (sudo; excludes `/cache`, `/localcache`, `/muc`, `/sessions`, `/temp`) | daily `01:20` | last 7 / daily 7 / weekly 4 / monthly 6 |

Why two repos rather than one with two tags: the hourly DB stream and the ~6 GB file stream must not
share locks/prune, and `system_probe` reports **one snapshot age per repo** — with a single repo a
stale file snapshot would hide behind the fresh hourly DB one.

Why a logical dump rather than the prepared set Task 7 named: it is the pattern already running in
production for `bnb-office.db` (daily, since 2026-10) and for the nightly LeagueSphere prod→stage
sync, it needs no compose change, and it restores into a freshly initialised container without the
system-DB/`--copy-back` trap that `mariadb-cross-env-restore` warns about.

Why `01:20` for files: it runs **after** the `00:40` dump, so the file set can only be a superset of
what the DB rows reference. `filedir` is content-addressed and never rewritten in place, so this
ordering cannot lose content.

## Consequences

### Positive

- Moodle content and DB now have hourly (DB) / daily (files) off-host snapshots with a real retention
  policy, plus Grafana alerting on both log freshness and **snapshot age**.
- The DB stream cannot silently go stale: the dump script rejects a dump under 10 MB or failing
  `gzip -t`, and the restic script exits 1 when `current/` is older than 2 h — a dead dump job no
  longer produces fresh-looking snapshots of old data.
- Restore is wired into the restic role, so a rebuilt host re-hydrates both halves automatically
  (with an operator notice for the manual import).
- The `restic` role is now safe for a *fourth* scope: the password check no longer assumes
  home/root/db, and the Storage Box `mkdir` list is derived from each repo's own URL.

### Negative / tradeoffs

- **No PITR.** `log_bin` stays off; the recovery granularity is one hour. Enabling `--log-bin` on the
  `db` command is a separate, rehearsed change.
- The hourly dump is a full 1.6 GB read (~2 min on prod) and a ~134 MB gzip write. `--skip-dump-date`
  + `gzip -n` keep the output byte-stable so restic de-duplicates it, but it is still CPU and disk
  churn every hour.
- The dataroot snapshot needs `sudo`, so those two scripts run privileged (same as the existing
  root/ls-db scopes).
- `restore.yml`'s "containers are running" guard keys off `dirname(docker-compose.yml)`, which does
  **not** match the moodle data paths. Only the empty-target rule (or an explicit `force_restore`)
  protects a live site — documented in `tasks/main.yml` and the AGENTS runbook.

### Implementation Details

**Files (PR #272, commit `98bdf32`)**

- `ansible/plays/vars/default.yml` — `moodle_enabled`, `moodle_data_root_path` (MODIFY)
- `ansible/plays/vars/secrets.yml`, `ansible/plays/vars/restic.yml` — password, two repo entries,
  schedules, retention, log paths (MODIFY)
- `ansible/plays/roles/restic/defaults/main.yml` — seed + Vaultwarden item + derived repo/log lists (MODIFY)
- `ansible/plays/roles/restic/tasks/{init,backup,main}.yml` — password-check fix, URL-derived sftp
  mkdir, stale-env/log cleanup, dump + two backup units, restore includes (MODIFY)
- `ansible/plays/roles/restic/templates/moodle_dump.sh.j2` (NEW), `restic_backup.sh.j2` — stale-source
  guard (MODIFY)
- `ansible/plays/roles/system/templates/restic_{forget,check}.sh.j2`, `roles/system_probe/defaults/main.yml`,
  `roles/testing/tasks/restic_check_recent.yml` (MODIFY)
- `monitor/provisioning/alerting/alert-rules.yml` — log-freshness + `restic-snapshot-alerts` (MODIFY)
- `ansible/plays/roles/user/tasks/moodle_data_dirs.yml` — `db-backup` directory (MODIFY)
- molecule `restic/default` (moodle enabled, three units asserted) and `no-leaguesphere` (moodle
  fixtures pre-seeded, removal asserted) (MODIFY)
- `moodle/AGENTS.md` + the hosting plan's Task 7 (MODIFY)

**Testing & verification (executed)**

- `ansible-playbook servyy.yml --syntax-check` on `production` and `testing`; `yamllint` clean for all
  touched files; every changed YAML parsed; templates rendered for all four host shapes
  (moodle/leaguesphere on/off) with a throwaway play against the real vars files.
- CI green (28 checks) after fixing the one molecule failure below.
- `servyy-test.lxd`: env files + both repos created, three timers active; dump 128 MB in 32 s;
  `moodle-db` snapshot 127.7 MiB, `moodle-files` 33.3 MiB / 2,815 files.
- **Restore drill (total loss)**: `docker compose down` → `moodledata`, `mariadb` and
  `db-backup/current` moved aside → the role's restore tasks for both scopes → fresh `moodle.db`
  initialised → dump imported (7 min) → app started. Result: 497 tables, 39,374 `mdl_files`, 104
  courses — identical to the pre-drill baseline; front page `HTTP 200` (`<title>Home | Flag Academy`);
  the restored tree differed from the moved-aside copy **only** in the 902 excluded cache files
  (0 non-excluded differences).
- Stale guard exercised: back-dating `current/` makes the unit exit 1 with
  `Source data is stale, refusing to snapshot`; un-touching it succeeds.
- `servy.lehel.xyz`: dump 134 MB in ~2 min; `moodle-db` 128.1 MiB; `moodle-files` **5.781 GiB in
  1:47**; `restic forget --dry-run` with both retention sets and `restic check --read-data-subset=10%`
  clean; Pushgateway shows `restic_snapshot_age_seconds{repo="moodle-files"}` / `{repo="moodle-db"}`
  and the three moodle log-freshness series; Grafana's provisioned rules contain the moodle
  conditions.

**Key learnings (all found the hard way)**

1. **`| default(x ~ y)` is eager.** `moodle_data_root | default(docker.remote_dir ~ '/moodle/data')`
   aborted the molecule converge with `'docker' is undefined` — the fallback is evaluated even when
   the variable is set. Use `{{ a if a is defined else b }}` (only the taken branch is evaluated).
2. **`lookup('password', 'vars/…')` resolves against `playbook_dir`.** A debug play run from `/tmp`
   silently created *new* seed files there and pushed those random values into Vaultwarden for
   home/root/ls_db/moodle. Repaired by re-running the real handler from `ansible/` (all four items
   verified to match the seeds again). Never run restic/Vaultwarden playbooks from outside `ansible/`.
3. **`--tags user.docker.repo` on prod `git reset --hard`s the checkout**, which reverts files Ansible
   renders *in place* — `monitor/provisioning/datasources/datasources.yml` is tracked with raw
   `{{ monitor.loki_tenant }}`, so the next Grafana start crash-looped (25 restarts) on
   `cannot unmarshal !!map into string` until `--tags user.docker.env.monitor` re-rendered it. Always
   follow a repo-sync-only deploy with that render (or don't restart Grafana afterwards).
4. **Grafana's file provisioning did not pick up the edited alert rules** on its own — the API kept
   serving the old expressions until the container was restarted.
5. **The host's sudo umask is 027**: the first dump landed `0640` in a `0750` dir and the restore
   notice's `gunzip` failed with *Permission denied* during the drill. The script now sets `0755`/`0644`
   explicitly.
6. **Moodle re-applies `$CFG->directorypermissions` (`02777`)** to the dataroot at boot, so a restored
   tree ends up `2777` instead of the import's `2770`. That is Moodle's own startup code, not the
   restore — do not "fix" it.
7. **`bw sync` can fail with `invalid_grant`** on the controller (stale CLI token). `bw logout` +
   `BW_CLIENTID/… bw login --apikey` fixes it; the role only tolerates "already logged in" on stderr.

### Known issues & limitations

- No PITR (see tradeoffs). Binlogs are the follow-up, not part of this change.
- `restic-backup-home.service` still exits 3 hourly on some hosts for unreadable files (a separate,
  pre-existing issue; `ac551ef` removed one source of it — opencode's root-owned `.ssh`).
- The first deploy of a brand-new scope on `servyy-test` must run `--tags restic.init,restic.backup`
  first: the restore tasks fail on a test host whose repo has no snapshots yet (intentional tripwire).

## Related Decisions

- `history/2026-06-22_leaguesphere-local-mariadb-migration.md` — why LeagueSphere's prod DB uses a
  physical prepared set; Moodle deliberately does not.
- `history/2026-10-08_restic-ls-db-stale-lock-recovery-and-snapshot-monitoring.md` — snapshot-age
  probing, which the new scopes plug into.

## Alternatives Considered

**One repo `restic-moodle` with tags `moodle-files` / `moodle-db`** — matches the original Task 7 text.
Rejected: forget/check/probe would need tag support added, and the snapshot-age probe could no longer
tell a stale file snapshot from a fresh DB one.

**Physical `mariadb-backup` prepared set (as Task 7 named)** — fast recovery, proven for LeagueSphere
prod. Rejected for now: needs a new `/backup` bind mount in `moodle/docker-compose.yml`, carries the
cross-environment `--copy-back` system-DB trap, and buys no PITR while `log_bin=OFF`.

**Removing the home-repo exclusion and letting `restic-home` cover the dataroot** — one fewer scope.
Rejected: hourly uploads of a 6 GB tree, no separate retention, and the unprivileged job cannot read
the root-owned dataroot anyway.
