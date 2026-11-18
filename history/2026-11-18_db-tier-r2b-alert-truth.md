# WP-8R R2b — what the R2 deploy verification exposed, and what it cost to make it true

**Date:** 2026-11-18
**Status:** Accepted
**Relates to:** [`2026-11-18_db-tier-work-packages.md`](../docs/plans/2026-11-18_db-tier-work-packages.md) (WP-8R R2),
[`2026-11-01_grafana-admin-password-drift.md`](2026-11-01_grafana-admin-password-drift.md) (the first admin-password drift),
[`2026-11-18_monitor-render-out-of-checkout.md`](2026-11-18_monitor-render-out-of-checkout.md) (why a monitor edit needs a restart)

## Context

WP-8R R2 replaced the alert file's `or` chains of literal repo/tenant/threshold values with
comparisons against series the probes push. The deploy looked green: 53 rules provisioned, the
new threshold/severity series present, the `-1` mapping fixed. Verification then found four
things that were **false in production while every dashboard stayed green**:

1. a rule R2 had retired was still firing-capable in Grafana's DB;
2. one repo's age metric had been wrong for hours — a permanent false positive;
3. the recipe used to verify anything in Grafana could not authenticate at all;
4. three dump-backed tenants still had **no dump-age series**: exactly the gap R2 claimed to close.

This entry exists because "the deploy said ok" and "the alerting is true" are different claims,
and only the second one is what the work package promised.

## A. The retired rule was never pruned — one condition, two high alerts

`stale_restic_db_snapshot` was deleted from `alert-rules.yml` by R2 but still existed in
`grafana.db` with provenance `classic-file-provisioning`, unpaused, `severity: high`, and an
expression that still named `repo="db"` / `repo="moodle-db"`.

**Grafana's classic file provisioning adds and updates rules; it does not delete a rule that
disappears from the file.** Evidence that it had had every chance to: the container was
restarted at 22:24:02, the file was last rendered at 20:41:02 (the rule's own `updated` column),
and the rule was still there afterwards.

Left alone, a stale `db` repo would have paged **twice**: once via the orphan and once via
`stale_restic_snapshot_high`. Two high pages for one condition is how an alert channel gets
muted.

The provisioning API cannot remove it, in either direction:

| Request | Result |
|---|---|
| `DELETE /api/v1/provisioning/alert-rules/stale_restic_db_snapshot` | `409 alerting.provenanceMismatch` — "cannot delete with provided provenance 'classic-api-provisioning', needs 'classic-file-provisioning'" |
| `PUT …/{uid}` with `X-Disable-Provenance: true` | `409 alerting.provenanceMismatch` — "cannot update with provided provenance '', needs 'file'" |

So it was removed with **Grafana stopped**, from a copy of `grafana.db` outside the container:
`alert_rule` (1 row), `alert_rule_version` (2), `alert_rule_state` (1), `provenance_type` (1);
`PRAGMA integrity_check` ok; restored with uid/gid `472:0`, mode `0640` (Grafana runs as 472 and
will not start on a root-owned DB — `docker cp` restores files as root).

Verified after start: **53** rules, the uid `404`, no duplicate uid in the list, and all 53
`health=ok` **with an evaluation timestamp** (`/api/prometheus/grafana/api/v1/rules`), i.e. the
survivors are still being evaluated, not merely stored.

## B. `home`'s medium alert was a false positive caused by our own test snapshot

Reported: `restic_snapshot_age_seconds{repo="home"}` ≈ 10 440 s while the newest real snapshot
was ≈ 1 612 s old.

Cause: `restic snapshots --latest 1` returns the newest snapshot **per `(hostname, paths)`
group**, and the probe read `[0]` of that array — the first *group*, not the newest snapshot. A
stray snapshot `03446243` with `hostname="localhost"`, left by a branch-rendered test earlier the
same evening, formed its own group, sorted first, and its age grew without bound for as long as
the new snapshots did not.

Two fixes, both applied:

1. `restic forget 03446243` in the `home` repo (88 snapshots remain, all `hostname=servy.lehel.xyz`).
2. The probe now takes the **maximum over the whole repo** (`restic snapshots --json` →
   `max(.time)`, compared as instants because restic prints each time with the offset of the host
   that made it), so a hostname or paths variation can never dominate the metric again.

Proof: `ansible/tests/system_probe/test_restic_snapshot_probe.py` renders the real template and
runs it against a two-group fixture with a fake `restic` that honours `--latest` the way the real
one does (newest per group). Against the old `[0]` code it reports **10 800 s** for a repo whose
newest snapshot is **2 160 s** old — the same failure shape as production; against the fix it
reports 2 160 s. A second case pins the empty repo to `-1` (unverifiable, which pages) rather than
a silent 0.

Measured after the deploy: `restic_snapshot_age_seconds{repo="home"}` = **2 526 s** and
`Stale Restic Snapshot` went `firing` → `inactive` at its next evaluation.

## C. The Grafana admin password had drifted from the rendered env

`GF_SECURITY_ADMIN_PASSWORD` in the container env answered **401** on
`/api/v1/provisioning/alert-rules`, so the documented verification recipe could not work and the
orphan rule in (A) had to be found by reading `grafana.db`.

The drift, reconstructed from the DB and `grafana.log` (no secret was read for this):

| Time (UTC) | Evidence | Reading |
|---|---|---|
| 2026-11-01 11:29 | `monitor/grafana.env` mtime; content == the controller seed | env has not moved since the first drift was reconciled |
| 22:04:45 | `POST /api/v1/eval`, `uname=admin`, `remote_addr=[::1]` | the env value **did** authenticate earlier that evening |
| 22:08:38–22:10:05 | 4 × `POST /login` → `401 password-auth.invalid` | a browser login with something else failed |
| 22:12:49 | `user` row `updated`; 22:12:50 request referring to `/user/password/reset?code=…` | the admin password was **rewritten through the browser reset flow** |
| 22:33 | `grafana cli admin reset-admin-password --password-from-stdin` from the container's own env | env and DB agree again (200) |

Root cause, and the reason the recipe was fragile by construction: **Grafana applies
`GF_SECURITY_ADMIN_PASSWORD` only when it creates the admin user.** Afterwards the credential
lives in `grafana.db` and moves independently — UI change, password-reset link, or
`grafana cli admin reset-admin-password`. Nothing in a deploy asserted the two agreed, so "env
value 401s" was a permanent, silent state that looked like a wrong password.

**Decision: reconcile, deterministically, in the deploy.** New role
`ansible/plays/roles/monitor_grafana_auth` (tag `user.docker.monitor`, runs after
`monitor_reload`):

1. authenticate as admin with the **container's own** `GF_SECURITY_ADMIN_PASSWORD` (the secret is
   expanded inside the container's shell — never a controller-side secret, never argv);
2. only on a 401, re-assert it into the DB:
   `printf %s "$GF_SECURITY_ADMIN_PASSWORD" | grafana cli admin reset-admin-password
   --password-from-stdin`, with `no_log: true` so the CLI's settings dump stays out of the log;
3. prove the API answers 200 and **fail the deploy** (naming the trap) if it still does not.

A **service-account token** was the alternative. Rejected: it would have *routed around* the
divergence (verification would pass while the documented admin credential stayed dead), it adds a
new secret to provision and rotate, and it answers a question nobody asked — "can a machine read
the rules?" — when the actual contract is "the rendered env is the credential".

Accepted trade-offs: a repair logs out open admin browser sessions (Grafana rotates auth tokens on
a password change), and a deliberate UI password change is reverted by the next monitor deploy.
Both follow from the same invariant, which is now written down in `CLAUDE.md` and
`monitor/AGENTS.md`: **the rendered env is the credential; Vaultwarden is the copy you recover it
from, not a second source of truth.**

Verified, including the unhappy path: with the password deliberately drifted, the role reported
`changed=1`, repaired it, and the API answered 200; a second run was `changed=0` (idempotent).

## D. Three dump-backed tenants emitted no dump-age series

R2's promise was that "a new tenant row is covered by definition", but coverage comes from
`probe_minutes`/`severity`, and three tenants had neither. A dump that stops refreshing while its
restic snapshot keeps succeeding was unalerted for them.

| Tenant | Decision | Why |
|---|---|---|
| `bnb_office` | **Row added** — 26 h (1 560 min), `high` | Its dumps ride the hourly `home` snapshot, which keeps succeeding whatever the daily `dbops dump bnb_office` does, so no existing rule could see a broken dump. The dir is flat (`<dump_dir>` with timestamped `.sql.gz` files, no `current/`), the probe's fallback path is correct, and `cda` can stat it. ≥ 1 day of slack over the 02:30 cadence. |
| `leaguesphere` | **Row added** — 2 h (120 min), `high` | The "dump" is the `mariadb-backup` prepared set at `/var/jail/.../mysql-backup/current`. It is an hourly **atomic swap** (`mv new current`, `:40`), so the directory mtime *is* the refresh time; the dir is `0755 root:root` even though everything inside is root-only, so the unprivileged probe can stat it. The `db` repo's snapshot age could never cover this: restic happily re-uploads an unchanged stale set every hour. |
| `moodle` | **No row — written down instead** | `.../moodle/data/db-backup/current` sits behind `data/` at `0750 root:root`; the probe is a **user** timer (`system-db-dump-age.timer` as `cda`) and `stat()` is refused, so a row here would emit `-1` and page high forever — a false positive, not coverage. What it would take: run that one check as root (system unit) or grant the probe a sudoers/ACL stat on the path. The condition is not silent meanwhile: `restic['moodle-db']` carries the stale-source guard (`stale_guard_max_age_minutes: 120`), so a dump that stops refreshing **fails the backup job**, and `stale_restic_snapshot_high` pages on `repo="moodle-db"` at 2 h — a different signal, the same condition, and it depends on that guard staying. |

After the probe redeploy, Prometheus carries `db_dump_age_seconds` for **7** tenants
(bnb_office, dontforget, firefly, leagues_finance, leaguesphere, photoprism, queen), with
`db_dump_severity{tier}` for `business`=1, `high`=1, `private`=0. `bnb_office` reads 21 220 s
against its 93 600 s threshold (last dump 17:49, next 02:30) — a real measurement, not a page.

## Consequences

### Positive
- One condition, one page: the orphan rule is gone; 53 rules, all evaluating.
- The snapshot-age metric cannot be captured by a stray snapshot's `(host, paths)` group, and the
  regression is locked by a test that fails on the old behaviour.
- A monitor deploy now *proves* the Grafana admin credential works, and repairs the DB from the
  rendered env instead of leaving a silent 401 for the next operator.
- Every dump-backed tenant either emits a dump-age series or has its coverage explained where the
  next reader looks (`db_tenants.yml`, `monitor/AGENTS.md`, the WP-8R row).

### Negative / tradeoffs
- Removing a provisioned rule is a DB operation; there is no API path while provenance is
  `classic-file-provisioning`. Cheap, but it cannot be done from a laptop with only the token.
- The admin-auth reconciler overrides a deliberate UI password change on the next deploy.
- The probe still lists every snapshot per repo (fine at 10 repos / ~90 snapshots; a repo with
  tens of thousands would want a different approach).

### Known issues
- `moodle`'s dump age is unmeasured (see D); the guard-based coverage is indirect.
- `leaguesphere`'s dump-age series is a directory mtime — correct because the set is swapped, but
  a future in-place `mariadb-backup` would silently freeze it near zero. The comment in
  `db_tenants.yml` says so.

## Implementation details

**Repo:**
- `ansible/plays/vars/db_tenants.yml` — `probe_minutes`/`severity` for `bnb_office` and
  `leaguesphere`, plus the reasoning (and moodle's deliberate omission) as comments.
- `ansible/plays/roles/system_probe/templates/restic_snapshot_freshness.sh.j2` — `max(.time)`
  over every snapshot instead of `[0]` of `--latest 1`.
- `ansible/tests/system_probe/test_restic_snapshot_probe.py` — NEW: two-group fixture, empty-repo case.
- `ansible/plays/roles/monitor_grafana_auth/{defaults,tasks}/` — NEW: env→DB admin credential reconciler.
- `ansible/plays/user.yml` — the role runs after `monitor_reload` under `user.docker.monitor`.
- `monitor/AGENTS.md` — working verification recipe + the 401 trap; the "provisioning never prunes"
  section; the max-over-the-repo rule; per-tenant dump-age coverage.
- `CLAUDE.md` — recovery rule 6 now names the reconciler.
- `docs/plans/2026-11-18_db-tier-work-packages.md` — WP-8R row: R2b and what is still uncovered.

**Host (servy):**
- `grafana.db` — orphan rule's 5 rows deleted with Grafana stopped (backup copy at
  `/tmp/grafana.db.pre-r2b-20261118`).
- `home` restic repo — `restic forget 03446243`.
- probes redeployed (`--tags system.probe`): `system-restic-snapshots.sh`, `system-db-dump-age.sh`.
- Grafana admin password re-asserted from the container env (twice: the real repair, then once
  deliberately drifted to prove the role repairs, then repaired again by the role).

**Verification performed:**
- Grafana: 53 rules; uid `404`; no duplicate uid; 10 groups, all 53 `health=ok` with fresh
  `lastEvaluation`.
- `restic_snapshot_age_seconds{repo="home"}` 2 526 s; `Stale Restic Snapshot` `firing` → `inactive`.
- `db_dump_threshold_seconds` lists 7 tenants; `db_dump_age_seconds{tenant="leaguesphere"}` 55 s,
  `{tenant="bnb_office"}` 21 220 s vs 93 600 s threshold.
- `ansible-playbook plays/system.yml --syntax-check`, `plays/user.yml --check --tags
  user.docker.monitor`, and the new unit test all pass; the reconciler is idempotent (`changed=0`)
  when the credential is healthy.

**Key learnings:**
1. A provisioning file is not the whole rule set. A rule can be absent from the file the deploy
   just rendered and still be evaluating — the DB is the truth, and the file only prunes when
   someone prunes it.
2. `restic snapshots --latest 1` groups by `(host, paths)`. Any per-repo metric taken from it is
   only as good as the assumption that every snapshot shares one hostname.
3. An alert that cannot clear is worse than no alert: a false positive that grows forever teaches
   the operator to ignore the channel, and here it was caused by the test data of the work
   package itself.
4. When a verification credential 401s, the instinct to "just read the DB" is the moment
   verification quality collapsed. Fix the credential path, then verify.
5. "The deploy is green" is a statement about the deploy. Coverage claims have to be measured
   against the series that exist.
