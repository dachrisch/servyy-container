# WP-8R R7 + R8 — bnb leaves `home`, and one backup unit per tier (2026-11-19)

Branch `db-tier/wp8r-r7r8-hygiene` from master `f4092a61`. Both halves of the
package were implemented, deployed to `servy.lehel.xyz` and measured there.
**Nothing is merged yet** — the coordinator merges, then re-deploys from master.

## R7 — `bnb_office` gets its own repo and leaves the `home` file backup

### What `home` actually held (measured 2026-11-19, before the change)

`restic ls` of the newest pre-change snapshot (`f1806769`, 15:03) with the bytes
each path contributed:

| Path | Bytes in `home` | What it was |
|---|---|---|
| `servyy-container/photoprism` (datadir under it) | **812.0 MB** | the STOPPED pre-cutover PhotoPrism datadir — dead since WP-6; PhotoPrism has lived on `db-private.mariadb` since then, and its restorable copy is the `db-private` logical dump |
| `dbops-dumps/moodle-20261118T184549Z.sql.gz` | **136.0 MB** | an ad-hoc cutover dump of the Moodle database |
| `dump-offd-20261113.sql.gz` | **136.0 MB** | an ad-hoc hosting-move dump of the same database |
| `servyy-container/bnb-office/.backup` | **209 484 B** (4 files) | bnb's dumps: one flat timestamped `.sql.gz` per run, no `current/` |
| **total** | **1 084 MB** | |

`db-dumps` was already excluded (R3/R4/R6), and `db-*/data` and
`moodle/data` were excluded earlier. So these were the last dump bytes and the
last dead datadir riding a *file* backup.

Three consequences, in the order that matters:

1. **Scope.** A customer's bookkeeping data and two of our LMS dumps sat inside a
   filesystem backup whose cadence and coverage are properties of `/home`.
2. **Retention.** `home` keeps 24 last + 48 hourly + 14 daily + 8 weekly +
   6 monthly. bnb's own promise (the plan, 2026-11-18) is 30 dailies + 8 weekly +
   6 monthly — i.e. the dump was kept for *`home`'s* lifetime, not the tenant's
   and not the contract's.
3. **Churn.** A timestamped dump file is a NEW blob for restic even when the SQL
   is byte-identical, so each run added its bytes to `home`. Measured: 52 357 B
   per run for bnb (the 2026-11-19 02:34 file and the 2026-11-19 15:35 file have
   the same md5, `36e1154…`), i.e. the mechanism, not the size, was the defect.

### What changed

* **New repo `db-bnb`** (`backup_targets`), name in the same short form as
  `db-lf`/`db-queen`, so it does not track the app's directory name.
  Retention **`db_daily` = 30 daily + 8 weekly + 6 monthly** — the plan's own
  decision ("bnb keeps the same retention as the private tenants"); it is a named
  profile in `retention_profiles`, never an inline map, so a typo fails
  `plays/tasks/restic_wiring.yml` instead of pruning at another rate.
  Initialised on the Storage Box by the existing generic `restic init` loop —
  adding the row is the whole wiring (`env.db-bnb` rendered, repo created,
  password verified against the D16 `restic_password_db`).
* **bnb's dump moved to the canonical root**
  `/home/cda/db-dumps/bnb_office/{new,current}` — chosen over "stay in
  `.backup/`" because it makes every tenant identical: `<dump_dir>/current` is
  the only thing any tenant repo snapshots, the size floor + `new/` → atomic
  `current/` swap apply, and the wiring guard
  `restic.<repo>.source_path == <dump_dir>/current` covers it. The dump-age probe
  needed no change: it already prefers `<dump_dir>/current` when it exists, so
  bnb moved from its fallback path to the primary one (measured after:
  `db_dump_age_seconds{tenant="bnb_office"} = 10`).
* **`home` excludes** (`vars/restic.yml`): `servyy-container/bnb-office/.backup`,
  `servyy-container/photoprism/database`, `dbops-dumps`, `dump-offd-*.sql.gz`.
* The legacy flat dumps were then **deleted** (4 files, 208 KiB): the newest of
  them is md5-identical to the dump now in `db-bnb`, and that repo was
  restore-drilled before the deletion.

### Proof (measured on servy)

| Check | Result |
|---|---|
| bnb's dump appears in the new repo | snapshot `8c0dafca` in `db-bnb`, 2026-11-19 16:29:00, 51.130 KiB, path `/home/cda/db-dumps/bnb_office/current/bnb_office-20261119T143533Z.sql.gz` |
| …and vanishes from `home` | `restic ls` on snapshot `a9217bf5` (16:01, first after the exclude) returns nothing for all four paths; the pre-change snapshot `f1806769` still lists them (that is retention, not the exclusion) |
| `home` shrinks by ~the dump size | snapshot `f1806769` **7.375 GiB** → `a9217bf5` **6.366 GiB** = **−1.009 GiB**, attributed by `restic ls -l --json` per path: photoprism **812.0 MB**, `dbops-dumps` **136.0 MB**, `dump-offd-…` **136.0 MB**, bnb `.backup` **0.2 MB** (total **1.084 GB**, the plan's "~1.1 GB") |
| per-table counts identical after a restore | `restore-drill.sh --tenant bnb_office` → `bnb_office ok 33.0 s 8c0dafca…`, structure identical, no populated table empty, equal-count tables checksum-equal against the live `ibs` |
| drill still passes for the tenant | yes — that IS the drill for `bnb_office`; its `drill: monthly` row is unchanged |
| probes after the change | `db_dump_age_seconds{tenant="bnb_office"} = 10` (threshold 93 600), `db_dump_severity{tier="business"} = 1`, `restic_snapshot_age_seconds{repo="db-bnb"} = 1 149` (threshold 93 600, severity 1), `system_log_freshness_seconds{log="dump-bnb_office"} = 463` and `{log="restic-backup-db-bnb"} = 1 157` (both threshold 93 600), `db_dump_probe_success = 1` |

Honest note on churn: `restic diff` on `home` is 6 files / 20.6 MB for
14:00→15:03 and 17 files / 20.5 MB for 16:01→16:49. bnb's contribution to that
was ~52 KB/day, so **the diff numbers barely move**; what R7 buys is scope,
retention and 1.084 GB of dead weight per snapshot. The ~20 MB/h that remains is
other home data and is *not* explained by this package — recorded as a follow-up.

## R8 — one `db-backup@<tier>` unit per tier

### Shape

* `db-backup@.service` + `db-backup@.timer` (a real systemd template pair,
  `%i` = tier), deployed once, enabled per tier: `db-backup@business.timer`,
  `db-backup@private.timer`. **High and nonprod deliberately have no instance**:
  the high tier's protection is R5's physical prepared set + 5-minute binlog
  tail (their own units, untouched), and nothing dumps nonprod by design.
  The roster is derived from `db_tenants[*].dump_via` + the host's enabled repos,
  so a tier with no `dbops` tenant gets no unit and a converged tenant needs no
  edit here.
* The timer fires every 5 minutes (`OnCalendar=*-*-* *:00/5:00`,
  `RandomizedDelaySec=0`) and `db-backup-tier.sh <tier>` asks
  `dbops dump-due <tier>` who is due, then runs each tenant's **existing**
  `dump-<tenant>.sh` serially under **one global `flock`**
  (`~/.cache/db-backup.lock`): a tick that finds the lock held exits 0 and leaves
  its tenants for the next tick, so two tiers can never dump at once.
* Per-tenant failure isolation: each tenant is a child process; a failure is
  logged and the loop continues; the unit ends non-zero if *any* tenant failed.
* Stale-source guard semantics preserved, not re-invented: the runner never
  writes a dump itself. Each tenant's generated script still writes into `new/`,
  enforces its size floor, proves the file, and only then performs the atomic
  `mv new current` — so a killed dump leaves `current/` at the last good set, and
  the dump-age probe turns the ageing copy into a page. The repos that already
  carry restic's own stale-source guard (`moodle-db`, `ls-binlog`) keep it.
  The high tier's `mariadb-backup` set, the `binlog-ship` 5-minute pair,
  `expire_logs_days` and `--keep-within 2d` were not touched.

### The "due" computation (no times re-hardcoded)

`dbops dump-due <tier>` walks the tenant inventory in **inventory order** and
prints the tenants of that tier with `dump_via: dbops` whose prepared set is
older than their last scheduled instant:

* `dump_schedule: 'daily HH:MM'` → the most recent `HH:MM` (today, or
  `yesterday HH:MM` — `date -d "yesterday …"`, not `-86400`, so a DST changeover
  cannot make a daily tenant look due for an extra hour);
* `dump_schedule: 'hourly'` + `dump_at: 'MM'` → the most recent `MM` past the
  hour;
* due ⇔ `<dump_dir>/current` is missing, or its **mtime** (the atomic swap time —
  the same measurement the dump-age probe takes) is older than that instant.

Consequences: an immediate re-run is a no-op by construction; a run missed to a
reboot is caught up by the next tick (the comparison is against the schedule,
never "did the timer fire"); changing a dump time is one edit in
`plays/vars/db_tenants.yml`. A cadence `dbops` cannot parse is a hard failure
(the tenant name and the value are printed), never a silent skip.

`--force` exists for operators (and was used for the proofs): it returns every
`dbops` tenant of the tier. It is unreachable from the timer — `ExecStart` passes
only `%i`.

### Schedules kept (from the inventory, unchanged)

photoprism 00:45, bnb_office 02:30, leagues_finance 01:15, queen 01:25,
dontforget 01:35, firefly 01:45 — the row values, which is also what the plan's
table lists except for bnb (the plan's table says 01:05; the inventory and the
deployed timer have said 02:30 since WP-5b, and R8 preserves what the inventory
declares rather than inventing a time). moodle's hourly `:40` and leaguesphere's
physical `:40` are not in a tier unit. **bnb's 02:30 is inside the nightly
02:00–04:00 restic window** — pre-existing, recorded as a follow-up, not changed
here because it is not this package's decision.

### Units removed by the deploy (stopped, disabled, deleted)

`db-dump-photoprism`, `db-dump-leagues_finance`, `db-dump-queen`,
`db-dump-dontforget`, `db-dump-firefly` and the legacy `docker-bnb-office-dump`
(both `.service` and `.timer`). The per-tenant dump *scripts* stay — they are
what the tier runner executes. `moodle-dump`, `mariadb-backup-ls`, `binlog-ship`
and the restic snapshot units are untouched.

After the deploy, `systemctl --user list-timers` shows exactly
`db-backup@business.timer` and `db-backup@private.timer` for tier dumps, plus
`moodle-dump.timer`, `mariadb-backup-ls.timer`, `binlog-ship.timer` (the three
scopes R8 must not converge) and one `restic-backup-*` per repo.

### Proof (measured on servy, 2026-11-19)

1. **A real dump run per tier writes fresh dumps for the due tenants.**
   * business: `db-backup-tier.sh business --force` → `dumped=3`, rc 0, 16:40:35
     → 16:40:39: bnb_office 52 357 B (mtime 15:35:34 → 16:40:36),
     leagues_finance 11 621 B (11:05:29 → 16:40:38), queen 28 888 B
     (11:05:29 → 16:40:39).
   * private: `db-backup-tier.sh private --force` → `dumped=3`, 16:40:58 →
     16:42:10: photoprism 107 336 941 B (69 s), dontforget 24 527 B, firefly
     179 035 B. (The first automatic run, at 15:30, also proved the
     missing-`current/` path: bnb was due because it had no prepared set yet.)
2. **A second immediate run is a no-op.** `db-backup-tier.sh business` and
   `… private` at 16:42:56 → both exit 0 with `no tenant due`; every dump mtime
   unchanged (bnb 16:40:36, lf 16:40:38, queen 16:40:39, photoprism 16:42:07,
   dontforget 16:42:08, firefly 16:42:09). The 5-minute timer ticks produce the
   same line.
3. **A killed dump leaves `current/` untouched while the others complete.**
   Forced private run started 16:43:30; the photoprism dump script was SIGTERMed
   at 16:43:37 (`exit_code=143`, `tenant dump failed`). Result: photoprism's
   `current/` still holds `photoprism-20261119T154058Z.sql.gz` with mtime
   16:42:07 (the set from the previous good run); dontforget 24 769 B and firefly
   179 035 B completed afterwards; the run ended
   `tier run finished with failures tier=private dumped=2 failed=1`.
   The killed dump's child finished into `db-dumps/photoprism/new/`
   (107 336 941 B, 16:44) and was **never promoted**, which is the swap
   discipline doing exactly what it promises. The next successful run wipes
   `new/`.
4. **Restore drills still pass, one tenant per tier.** Monthly class:
   `bnb_office ok 33.0 s` (business, from `db-bnb`) and `photoprism ok 111.5 s`
   (private). `leagues_finance` 18.6 s, `queen` 19.6 s, `dontforget` 19.9 s also
   ok. **`firefly` failed once** with `dbops restore into the scratch server
   failed` (13.4 s; the log shows `ERROR 2002 … socket '/run/mysqld/mysqld.sock'`
   → `has_tables` read the empty answer as "already has tables") and **passed on
   the immediate retry in 53.7 s from the same snapshot** (`37587d55`). That is
   the R11 scratch-server readiness race, not this package — see follow-ups.
   The whole monthly class was then re-run from a clean `reset-failed` and every
   tenant passed from its own repo: **bnb_office ok 34.3 s** (`8c0dafca`,
   `db-bnb`), leagues_finance 20.3 s, queen 19.0 s, photoprism 109.4 s,
   dontforget 19.3 s, firefly 57.6 s — unit `Result=success`,
   `systemctl --user --failed` lists 0 units.

## Files changed

* `ansible/plays/vars/db_tenants.yml` — `db-bnb` target; bnb's row (repo, dir,
  `dump_at`, floor); `dump_via` on every tenant row; `dump_at` completed
  (`leaguesphere` `40`, `moodle` `40`, nonprod `''`); schema + policy comments.
* `ansible/plays/vars/restic.yml` — `db-bnb` repo, `db_backup_tier`/`dump_bnb_office`/
  `backup_db_bnb` schedules, two log keys, four new `home` excludes.
* `ansible/plays/tasks/restic_wiring.yml` — guards for `dump_via`, the due
  fields, `dump_at` shape, `dump_via: none` on a real tier, and the tier timer's
  schedule key.
* `ansible/plays/roles/restic/tasks/backup.yml` — tier roster + runner + template
  unit pair + per-tier log files + legacy unit removal; the dump timers are no
  longer generated per tenant.
* `ansible/plays/roles/restic/templates/db-backup-tier.sh.j2`,
  `db-backup@.service.j2`, `db-backup@.timer.j2` (new).
* `ansible/plays/roles/db_tier/templates/dbops.sh.j2` — `dump-due [--force]`,
  `last_scheduled_epoch`, per-row `dump_schedule`/`dump_at`/`dump_via`, and an
  inventory-order tenant list for the due walk.
* `ansible/plays/roles/user/tasks/docker_extras.yml` — the legacy bnb dump unit
  removed (with a pointer to where its removal happens).
* `ansible/plays/user.yml` — `user.docker.db-<tier>.render` tags so dbops can be
  re-rendered without running `docker compose up`.
* `ansible/plays/roles/restic/molecule/{default,no-leaguesphere}` — the tier unit
  rendered/absent, the legacy units removed/not created, the runner's lock and
  failure isolation asserted.
* `ansible/tests/dbops_dump_due/test_dump_due.py` + a CI step — renders the real
  `dbops.sh.j2` and proves due / no-op / catch-up / foreign-mechanism / `--force`
  / unparseable-cadence behaviour without Docker.

## Checks run

`ansible-playbook --syntax-check` on `servyy.yml`, `plays/user.yml`,
`plays/restic.yml`, `plays/restore_drill.yml`; `yamllint` on every changed YAML;
`ansible-lint --profile production` on `plays/roles/restic/`, `plays/restic.yml`,
`plays/tasks/restic_wiring.yml`, `plays/vars/{db_tenants,restic}.yml` → 0
failures; `bash -n` on the rendered `dbops`, `zsh -n` on the rendered
`db-backup-tier.sh`; `systemd-analyze --user verify` on `db-backup@.service` and
`db-backup@.timer` (only the expected "script not present locally" note for the
host paths); `python -m unittest` on the new fixture (6 tests); the three R1 typo
guards re-fired on demand against the live inventory (a repo name that is not a
target, an unknown retention profile, a malformed `dump_at` — each failed the run
with the offending value, and the file was restored byte-identically).

Molecule scenarios were extended but **not run here**: this workspace has no
Docker socket. `Molecule Test (db_tier/default)` remains broken for the unrelated
reason the coordinator is fixing on master.

## Deployment notes (for whoever re-deploys after the merge)

* `plays/restic.yml` (`--tags restic.init,restic.backup`),
  `plays/system.yml` (`--tags system.probe`), `plays/restore_drill.yml`
  (no tag filter; its tag is `restore.drill`) and the db_tier render pass
  (`--tags user.docker.db-business.render,user.docker.db-private.render`) all
  changed generated output. A restic-only deploy leaves the probes and the drill
  roster pointing at the old inventory — measured here: the drill ran bnb with
  `repo=home` until the drill play was re-deployed.
* **Deploy from a checkout that has the local-only seeds**:
  `ansible/plays/vars/.restic_password_*` and `.dbops_password_*` are
  `lookup('password', …)` files that are *not* in git. A fresh clone/worktree
  generates NEW values, and because the tier render pass writes
  `~/.dbops/<tier>.env`, that silently rewrote the backup users' passwords on the
  host (the MariaDB accounts keep the old ones) — business and private dumps then
  fail with `Access denied for user 'dbops_backup_<tier>'@'localhost'`. This is a
  second, undocumented reason for the "deploy from the canonical checkout" rule.
  Repaired here by symlinking the canonical seed files into the working copy and
  re-running the render pass (the root-password guard passed every time; no
  server was recreated).
* The host's own GitHub deploy key (`~/.ssh/id_servyy_container_deploy`) is
  **refused** by GitHub, so `--tags user.repo` cannot sync `/home/cda/servyy-container`
  and the host checkout is one commit behind master (`348ed29`). The deploy was
  therefore rendered from this branch's checkout on the controller. Worth fixing
  before the next host checkout is trusted.

## Follow-ups (not done here)

* `moodle-dump.sh` / `moodle-dump.timer` (WP-8R R9) and the high tier's
  physical set + binlog pair stay exactly as they were.
* bnb's dump time is 02:30, inside the 02:00–04:00 restic window. The plan's table
  says 01:05. Moving it is a one-value inventory change — but it is a schedule
  decision, so it is left to the owner.
* The drill's MariaDB scratch readiness can still race (`ERROR 2002 … socket`,
  then `has_tables` fails safe into "already has tables"): seen once in six
  drills, passed on retry. The readiness check authenticates, so the temporary
  init server is ruled out; a container that loses its socket after the check
  (memory pressure: 930 MB free of 7.7 GB during the drill) is the remaining
  explanation. Deserves its own fix, because it pages `db_restore_drill_failed`.
* `home` still adds ~20 MB per hour from sources this package did not identify
  (bnb's dump was 52 KB/day of it).
* `/home/cda/db-dumps/photoprism/photoprism-20261118T210223Z.sql.gz` (107 MB) is a
  stray dump in the tenant ROOT, outside `<dir>/current` — it is in no snapshot
  and no probe sees it. Not deleted here (it predates this package).
* `roles/restic/tasks/main.yml` still has a `Restore PhotoPrism Database` include
  pointed at the now-excluded `photoprism/database`. It is inert on a healthy host
  and the datadir is a rollback artefact, but deleting that datadir (with the WP-6
  window) should remove the include in the same change.

## Do not (measured traps this package hit)

* **Do not deploy a restic-only change and assume the probes/drills follow.** The
  probe lists and the drill roster are generated by other plays; re-deploy
  `system.probe` and `restore_drill` too.
* **Do not render `db_tier` from a checkout without the local-only seed files** —
  see the deployment note above. The root-password guard does not protect the
  backup users, and its `lookup('password')` values are not literal.
* **Do not add a per-tenant dump timer back.** `db-backup@<tier>` +
  `dump_due` is the mechanism; a second enabled timer can dump in parallel with
  the tier unit (`Persistent=true` catch-up).
* **Do not move Moodle onto the tier unit yet** (R9) and do not touch the high
  tier's `mariadb-backup` set, `binlog-ship`, `expire_logs_days` or
  `--keep-within 2d`.
* **Do not let the tier unit dump anything itself.** The floor and the
  `new/` → `current/` swap in the per-tenant script are the stale-source guard.
