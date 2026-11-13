# `enrol_waitlist` 4.5-b: the security bump, and what the four replacement candidates actually are

**Date:** 2026-11-13
**Status:** ✅ Accepted — deployed to `servyy-test.lxd` (rehearsal) and `servy.lehel.xyz` (production)
**Relates to:** [history/2026-11-10_moodle-waitlist-plugin-and-release-tooling.md](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md),
[history/2026-11-13_offd-cutover.md](2026-11-13_offd-cutover.md),
[moodle/plugins/README.md](../moodle/plugins/README.md), [moodle/AGENTS.md](../moodle/AGENTS.md)

## Context

The question was whether Christoph's `enrol_waitlist` could be *replaced* — the proposal on the table
compared Booking, Enrol by Category, "Enrollment Application" and Activity Signup. Reading the
candidate plugins turned up a second, more urgent fact: the version we were running is insecure.

Measured on production before the change (`mdl_*`, read-only):

| | |
|---|---|
| Installed plugin | `2025072001` = upstream tag `v4.5-a3` |
| `waitlist` enrolment instances | 52 courses — **14 active** (2026 F2/F3/F4 Lehrgänge), 38 disabled |
| `user_enrolments` through the method | **820** |
| Seat caps on the 14 active | 25–170 (one course exactly full at 25/25) |
| Live queue (`mdl_user_enrol_waitlist`) | **0 rows** — nobody waiting |
| 2027 intake | 13 courses created 2026-11-12 with `waitlist` instances, still `status=1` (not opened) |

Upstream issue [#16](https://github.com/emeneo/moodle-enrol_waitlist/issues/16) (2026-04-27) reported
five holes in exactly the files OFFD uses, and `2025072001` has all of them:

1. `enroluser.php` — `require_capability()` calls **commented out** while add/remove enrol still runs,
2. `users.php` — no access control, "user list and email data are exposed",
3. `unenrol.php` — unenrol executes without capability validation,
4. `profile/assign.php` — state-changing POST without CSRF protection,
5. `faculty.php` — public JSON endpoint, no `require_login()`.

Upstream fixed all five in a single commit, `1bfd5b5a43` (2026-05-12, "Security fixes"),
`version.php` → `2026051200`, release `4.5-b`.

## Decision

1. **Bump the vendored archive to `2026051200`, now.** It is a security fix, not a feature change,
   and the whole jump is one upstream commit. `db/install.xml` is byte-identical between the two
   versions and `xmldb_enrol_waitlist_upgrade()` has no step in that range, so the upgrade Moodle
   runs once on the next boot is version bookkeeping — no schema change, no data migration.
2. **Do not replace the plugin now.** The 2027 intake is being configured, and every candidate is a
   different shape plus a data migration (below). Replacing it is a separate decision, made between
   intakes, with a rehearsed import.
3. **Pin the archive by commit sha, not by tag.** Upstream's tags do not match their contents:
   tag `v4.5b` holds `version 2025072000`, i.e. something *older* than the `v4.5-a3` we are replacing.

## Consequences

### Positive

- The five holes are closed on a live site that holds 4 145 active user accounts (4 248 rows in the
  source dump). Verified after the deploy: `faculty.php` and `enroluser.php` answer `303` (login
  redirect) to an unauthenticated request instead of returning data, and `users.php` no longer
  renders without a capability check.
- Nothing about OFFD's data changed: 14 active + 38 disabled instances and all 820 `user_enrolments`
  are still there, `enrol_get_plugins()` still returns `manual,guest,self,cohort,waitlist`, the
  German instance label still renders (`get_instance_name()` → `Warteliste`), `upgrade.php
  --is-pending` is 0, cron exits 0.
- Students keep their path: `unenrolself` resolves to 1 for a real student in an active waitlist
  course (checked with `has_capability()` against production course contexts).
- The bump is now a documented, repeatable procedure (README + AGENTS.md) instead of one person's
  shell history.

### Negative / tradeoffs

- **A security fix can take access away.** The restored checks require `enrol/waitlist:manage` /
  `:unenrol`, which land on the `editingteacher`/`manager` archetypes. Checked before deploying:
  `manager` (role 1) passes both in production; the role *definitions* of `editingteacher` (3) and
  the custom `landesverband` (12) hold both at system context. The non-editing `teacher` role (4,
  3 users in waitlist courses) does **not** hold them and loses the admin pages it could reach while
  the checks were commented out. That is the intended behaviour, but it is a behaviour change.
- **Still a Moodle 5 dead end.** `$plugin->requires = 2024083000`, release line `4.5-b`, no `5.x`
  branch, no licence metadata in the repo, one small maintainer. The 5.x move has to resolve this.
- A 125 727 B GPL binary in a public repo, as before — the sha256 is the contract.
- The archive is one step *ahead* of `mdl_config_plugins` on the DB we imported, so a future bump
  may no longer be free: it needs the same `install.xml` + `upgrade.php` check first.

### Implementation Details

**Files (commit `f25854e`)**

- `moodle/plugins/enrol_waitlist-2026051200.zip` (NEW, 125 727 B, sha256 `2266fa07…c090`, 53 files),
  `enrol_waitlist-2025072001.zip` (DELETED)
- `ansible/plays/vars/default.yml` — `moodle_plugin_enrol_waitlist_{zip,sha256}` + the reasoning
  (MODIFY)
- `moodle/plugins/README.md` — provenance table, sha-based rebuild recipe, bump procedure (MODIFY)
- `moodle/AGENTS.md` — plugin section: version, commit, what the security fix was, the three
  constraints (MODIFY)
- `ansible/plays/roles/docker_service/templates/moodle.app.env.j2` — comment: a newer zip means the
  plugin's own upgrade runs, which needs the `install.xml`/`upgrade.php` check (MODIFY)
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` — fixture filenames
  (MODIFY, 4 occurrences)
- `history/2026-11-13_moodle-enrol-waitlist-security-bump.md` (NEW)

**Testing & verification (executed)**

- `ansible-playbook servyy.yml --syntax-check -i testing` clean; `yamllint` clean on the three
  touched YAML files.
- **Rehearsal on `servyy-test.lxd` first** (`./servyy-test.sh --tags user.docker.repo,user.docker.moodle`):
  boot log `Installing plugin enrol_waitlist from file:///opt/moodle-plugins/enrol_waitlist-2026051200.zip`
  → `Successfully installed enrol_waitlist`; container healthy, 0 restarts; `mdl_config_plugins` →
  `2026051200`; `--is-pending` rc 0; every installed `*.php` passes `php -l` (no syntax errors);
  site 200; `faculty.php` unauth → 303.
- **Production** (`./servyy.sh --tags user.docker.repo,user.docker.moodle --limit servy.lehel.xyz`):
  same boot lines, container healthy 0 restarts, `offd.de` 200. `https://offd.de` was **502 for ~60 s**
  during the boot: the image puts the site in CLI maintenance mode while `upgrade.php` runs, which is
  expected for a plugin upgrade and ended on its own (log: `== Wartungsmodus ==` … `Der Wartungsmodus
  wurde beendet`).
- Post-deploy on production: plugin `2026051200`; instances 14 active / 38 disabled; 820
  `user_enrolments`; `--is-pending` 0; `enrol_get_plugins()` = `manual,guest,self,cohort,waitlist`;
  `get_instance_name()` → `Warteliste` for course 75 (cap 45); `php -l` clean on the installed tree;
  `cron.php` rc 0; `enroluser.php`/`faculty.php` unauth → 303.
- `--tags user.docker.env.monitor` re-run afterwards (the known `--tags user.docker.repo` side
  effect): 0 unresolved `{{ monitor … }}` renders left in the Grafana provisioning tree.

**Key learnings**

1. **The deploy can never be ahead of git — and the assert says so, loudly.** The first `servyy-test`
   run failed with *"moodle/plugins/enrol_waitlist-2026051200.zip is missing"*: `repository.yml`
   checks out **the branch this working copy is on** (`git -C <local_dir> rev-parse --abbrev-ref
   HEAD`) from origin, so an uncommitted (even staged) archive simply isn't on the host. Commit and
   push *before* deploying, or the sha256 assert is the only thing you will see.
2. **Upstream tags in this project are not trustworthy.** `v4.5b` points at a commit whose
   `version.php` is `2025072000` — older than `v4.5-a3`'s `2025072001`. Pinning the *commit sha* and
   recording it next to the sha256 of the zip is what makes the bump reproducible.
3. **`moodle.org/plugins/<id>/versions/<v>/download` still 404s from here and from the server**, as it
   did in October. GitHub is the source of truth for this plugin; the repo keeps the rebuild recipe.
4. **A security patch deserves the same data check as a schema change.** Reading `install.xml`
   (identical) and `upgrade.php` (no step in range) before deploying turned a "will this migrate my
   DB?" question into a yes/no answer. Without it, "one version ahead of the DB" is exactly the
   failure the 2026-11-10 entry warned about.
5. **Capability changes are data.** The visible effect of the fix is not in the code we shipped but in
   `mdl_role_capabilities`: OFFD's custom `landesverband` role already held `manage`/`unenrol`, so no
   trainer was locked out — that had to be checked in the DB, not assumed from the archetypes.
6. **The live queue is empty, which makes a later swap cheaper than it looks.** `mdl_user_enrol_waitlist`
   has 0 rows, so replacing the enrolment method later means remapping `mdl_enrol` instances and 820
   `user_enrolments` — but no queue state. Doing it while the 2027 courses are still `status=1` is the
   cheapest window; doing it after they open means migrating whoever is in the queue.

### Rollback

Moodle does not downgrade a plugin: once the boot wrote `2026051200` into `mdl_config_plugins`, older
files on disk leave the site claiming a version mismatch. Because this bump changed **no** schema and
`db/install.xml` is identical across the two versions, the cheap rollback is a code + version-number
revert, not a DB restore:

```bash
# 1. restore the old archive in git and pin the old vars, then deploy the repo again
git revert <this-commit> && git push origin master
cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.moodle --limit servy.lehel.xyz
# 2. tell the DB it is back on the old plugin version (only safe because install.xml is unchanged)
ssh lehel.xyz "docker exec -i moodle.db sh -c 'exec mariadb -uroot -p\"\$MARIADB_ROOT_PASSWORD\" -D moodle'" \
  <<'SQL'
UPDATE mdl_config_plugins SET value='2025072001' WHERE plugin='enrol_waitlist' AND name='version';
SQL
```

The container must restart afterwards (any restart re-runs the entrypoint that installs `PLUGINS=`,
so `docker restart moodle.moodle` suffices). Do **not** take this path for a bump that changed the
schema — restore the hourly `restic-moodle-db` dump instead ([moodle/AGENTS.md](../moodle/AGENTS.md),
"Restore runbook").

### Known issues & limitations

- `teacher` (role 4) can no longer reach the waitlist admin pages. If OFFD staff actually use that
  role for enrolment work, grant `enrol/waitlist:manage`/`:unenrol` to it — a capability change, no
  code.
- `mdl_waitlist_info_field` / `mdl_waitlist_info_data` exist and are empty (legacy tables from the
  plugin's pre-2024 custom-field era); the 110 courses using a course custom field do so through
  **core** `mdl_customfield_*` (`core_course`, field `Association`), which is independent of the plugin.
- `RESUME_LATER.md` still describes the pre-cutover handoff ("expected version `2025072001`") and is
  stale; it was left untouched.

## Alternatives Considered

The four candidates, checked against their own sources rather than the comparison table:

| Candidate | Declared Moodle | Automatic promotion | Course enrolment | Verdict |
|---|---|---|---|---|
| **Booking** `mod_booking` 10.0.8 | `$plugin->supported = [405, 503]` — 4.5–5.3 | ✅ "waiting lists that move up automatically" (free tier) | ✅ as an action of a booking option — it is an **activity**, not an enrol method | Only candidate that is both 5.x-ready and does real promotion. Needs `local_wunderbyte_table`, Free/Pro ($400/yr) split for approvals, slots, certificates. A project: booking option per Lehrgang + catalogue; the seat cap moves out of the enrolment instance |
| **Enrol by Category** `enrol_bycategory` | 3.9–5.2 | ⚠️ no FIFO promotion: a daily 14:00 task emails the next 5 waiters and the fastest click wins (max 5 notices) | ✅ self-enrol variant, can require completion in a category, auto-joins a group | Correct only if the real requirement is progression ("finished F3 → may book F4"); its waitlist is a race, weaker than what we have |
| **Enrollment Application** | *no such plugin found*; closest is `enrol_apply` ("Enrolment upon approval"), **2.1–4.1** | — (manual approval per application) | ✅ | Cannot even run on 4.5.16. The table's "5.3" row does not correspond to a plugin |
| **Activity Signup** `mod_signup` | 4.5–5.3, GPL-3, first release 2026-10 | ✅ **per group** (capacity per group, first waiter promoted when someone leaves, Lock API against overbooking) | ❌ never enrols into the course | Complementary, not a replacement — useful if people must be allocated into groups/sessions inside a course |

**Keep `2025072001`.** Rejected: it is the vulnerable version, and the fix is one commit upstream.

**Fork the plugin ourselves / patch the five files locally.** Rejected: upstream shipped exactly
those fixes on 2026-05-12; carrying a private fork of an enrolment method is a maintenance cost with
no upside.

**Swap to Booking now.** Rejected for timing, not for fit: 13 courses for the 2027 intake were created
the day before this change and are about to open, and the swap needs the 52 instance rows and 820
`user_enrolments` migrated. It is the recommended target *if* a Moodle 5 move is scheduled — as its
own decision, between intakes.

## Related Decisions

- [2026-11-10](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md) — why the plugin is vendored
  and installed at boot from `PLUGINS=`, and why the zip root must be `waitlist/`.
- [2026-11-13_offd-cutover.md](2026-11-13_offd-cutover.md) — the instance this runs on.
- [docs/plans/2026-11-13-moodle-final-drop-release.md](../docs/plans/2026-11-13-moodle-final-drop-release.md)
  — the import path that created the `2025072001` row this bump moves past.
