# `enrol_waitlist` installed from a vendored archive, and the release tooling that ships with it

**Date:** 2026-11-10
**Status:** ✅ Accepted — plugin deployed to `servy.lehel.xyz`; scripts delivered by repo sync
**Relates to:** [docs/plans/2026-11-13-moodle-final-drop-release.md](../docs/plans/2026-11-13-moodle-final-drop-release.md),
[history/2026-11-04_moodle-moodledata-ingested.md](2026-11-04_moodle-moodledata-ingested.md),
[history/2026-11-06_moodle-restic-scopes.md](2026-11-06_moodle-restic-scopes.md)

## Context

The rehearsed instance on `m.leaguesphere.app` had Christoph's real database and real moodledata,
backups with a drilled restore, and a measured wwwroot rewrite — but the database referenced a
plugin whose code existed nowhere on the host. `mdl_config_plugins` says `enrol_waitlist`
`2025072001`, `mdl_config.enrol_plugins_enabled` already lists `waitlist`, and 35 `mdl_enrol` rows
use it: **21 active** (the 2026 F2/F3/F4 Lehrgänge) with **820 `user_enrolments`**. Runtime check
before the fix: `enrol_get_plugins()` returned `manual,guest,self,cohort` — the enrolment method was
simply absent, so those courses could not cap seats, queue applicants or promote from a waitlist.

The blocker had been parked as "ask Christoph for the zip", because `moodle.org/plugins/download.php`
returned 404 to both this machine and servy during the October work. That turned out to be wrong:
the plugin's GitHub repository sits behind the Marketplace, and the dump's version number maps
exactly onto a tag.

The second half of the request was the Friday procedure itself: the final dump arrives 2026-11-13
and must be *both* the last import and the release. Every step had been done once by hand, in prose,
with nothing executable in the repo.

## Decision

1. **Vendor the exact plugin version in git** and let the image install it from a `file://` URL at
   every boot, instead of downloading at boot or copying into a running container.
   `version.php` in tag **`v4.5-a3`** (`03cf4161`) is `2025072001`, `requires 2024083000`,
   component `enrol_waitlist` — the same version the database already knows, so registration is a
   no-op rather than a plugin upgrade against Christoph's data.
2. **Pin the artifact by hash** and assert it during deploy, because the failure mode is not a
   broken page: `015-copy-plugins.sh` exits 1 and the **container never starts** (nginx 502,
   healthcheck red, Traefik withdraws the router). The other quiet failure — swapping the archive
   without bumping the version — would run the plugin's upgrade steps against a live DB.
3. **Ship the import as scripts in the repo** (`moodle/scripts/`), delivered by the normal repo
   sync, and write the ordered procedure as a plan doc. The scripts deliberately refuse to touch
   `SITE_URL`, the router or DNS so the import can be verified on the rehearsal hostname before
   anything public changes.

## Consequences

### Positive

- The 14 active Lehrgang courses have their enrolment method again: `course 75 -> manual,waitlist,self`,
  `enrol_get_plugins()` → `manual,guest,self,cohort,waitlist`, version `2025072001`, no pending
  upgrade, container healthy with 0 restarts. The plugin's own page answers
  `303` (login redirect) and `get_instance_name()` returns the German `Warteliste`, i.e. lib and
  lang files are in place.
- No boot depends on an external download, and an image bump cannot delete the plugin — the same
  reason the docroot stays immutable.
- The release gate is executable and was exercised against the known-good 2026-11-04 export
  (PASS: 9 498 filedir hashes, 9 317/9 317 DB hashes present, 181 orphans) and against a synthetic
  ASCII-mangled archive and a truncated dump (both FAIL with the reason).
- Friday's failure modes now have names: truncated upload, ASCII-mangled files, transient
  directories, missing content hashes, a dump that is not a plain `mdl_` data dump.

### Negative / tradeoffs

- A 125 KB GPL binary lives in the repo. It is deliberate (reproducibility over purity) and the
  rebuild recipe is in `moodle/plugins/README.md`, but it is a binary in a public repo — a reviewer
  has to trust the sha256.
- The archive's shape is an implicit contract with the image's installer (`waitlist/` at the root).
  Documented in three places, tested in molecule, but it is an upstream-implementation detail.
- `qbehaviour_adaptiveallnothing` is still absent on purpose (no quiz uses it), so Moodle keeps
  one "missing from disk" notice.
- `import-offd-release.sh` is reviewed but **not yet run against a fresh export on the test host**;
  that rehearsal is the remaining pre-Friday item.

### Implementation Details

**Files (PR #281)**

- `moodle/plugins/enrol_waitlist-2025072001.zip` (NEW, 125 173 B, sha256 `0267ccb9…2663`),
  `moodle/plugins/README.md` (NEW: provenance, rebuild recipe, bump procedure)
- `moodle/docker-compose.yml` — bind mount `./plugins:/opt/moodle-plugins:ro` (MODIFY)
- `ansible/plays/roles/docker_service/templates/moodle.app.env.j2` — real `PLUGINS` value (MODIFY)
- `ansible/plays/vars/default.yml` — `moodle_plugin_enrol_waitlist_{zip,sha256}`,
  `world_readable_paths_by_service.moodle` += `plugins` (MODIFY)
- `ansible/plays/roles/user/tasks/moodle_plugins.yml` (NEW: stat + sha256 assert, clear fail_msg),
  `roles/user/tasks/main.yml` (import, tag `user.docker.moodle`) (MODIFY)
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` — renders the real
  `moodle.app.env` and asserts the `PLUGINS` line + 0775/0664 modes (MODIFY)
- `moodle/scripts/{verify-offd-export,import-offd-release,wwwroot-replace}.sh` (NEW)
- `docs/plans/2026-11-13-moodle-final-drop-release.md` (NEW), `moodle/AGENTS.md` (MODIFY)

**Testing & verification (executed)**

- Template rendered with the real vars/secrets through the real role (throwaway play): `PLUGINS` and
  the archive modes came out right before anything was deployed.
- `ansible-playbook servyy.yml --syntax-check` on `production` and `testing`; `yamllint` clean.
- Deployed with `--tags user.docker.repo,user.docker.moodle` (then `user.docker.env.monitor`, see
  learning 3): boot log `Successfully installed enrol_waitlist to /var/www/html/enrol/waitlist`,
  container healthy, 0 restarts, `curl file://` proven inside the image (curl 8.22.0) *before*
  wiring it.
- Post-deploy: `enrol_get_plugins()` includes `waitlist`; all 14 active waitlist courses expose the
  method; `upgrade.php --is-pending` rc 0; site 200; cron still running (41 tasks in 30 min).
- `verify-offd-export.sh`: PASS on the real archive; FAIL on a synthetic archive whose file content
  does not match its filename; FAIL on a dump with no `mdl_` schema.

**Key learnings**

1. **A missing plugin is invisible until it matters.** The container was healthy, the site was 200,
   and no error appeared in the logs — the method was just gone from `enrol_get_plugins()`.
   Checking plugin references against the installed code is part of importing someone else's DB.
2. **The image's plugin installer has an undocumented contract**: `mv "$plugin_subdir"`, so the zip
   root must be the plugin's subdir. GitHub's archive of a tag is *not* shaped that way; `curl | tar`
   would have produced a container that refuses to start.
3. **`curl file://` works in the Alpine image** — verified in the running container instead of
   assumed, which is what made the no-external-download design safe.
4. **The pull-based delivery is the point.** Mid-way a `scp` of the scripts onto servy was
   rejected: the git checkout is the deploy artifact, and untracked files in it are drift the next
   `git reset --hard` silently hides. Scripts were removed from the host and delivered by
   `--tags user.docker.repo`.
5. **A concurrent session owned the checkout.** The scripts commit briefly landed on another
   session's `fix/fail2ban-sshd-session` branch; it was moved to this branch and that ref restored
   to its remote head before pushing. `git status`/`git branch --show-current` before committing is
   not optional in this repo.
6. **`--tags user.docker.repo` still reverts the Grafana provisioning renders** (learning 3 from the
   restic entry, confirmed again): `datasources.yml` came back with raw `{{ monitor.loki_tenant }}`
   and needed `--tags user.docker.env.monitor` immediately after.
7. **A privileged path guarded by an unprivileged test is wrong again** — the exact class of bug the
   dump script had (learning 8 in the restic entry). `data/` is `root:root 0750`, so
   `[[ -d $DATA_ROOT/moodledata ]]` and `stat` on the rollback dump answered "no" for `cda` and the
   import script aborted with "cannot resolve the moodledata root" even though both paths were
   correct. Caught by adding `--dry-run` and running it against the real export on the host, not by
   reading the code. Every test below the data root now goes through `sudo`.

## Alternatives Considered

**Ask Christoph for the plugin zip.** Original plan. Rejected once the exact tag was identified:
it converts an external dependency into a pinned artifact, and avoids two people verifying the
same binary by hand.

**Download from moodle.org at boot (`PLUGINS=<https URL>`).** Matches upstream docs and needs no
repo binary. Rejected: the endpoint 404s from this network *and* from the server, and a boot-time
download makes image rebuilds dependent on a third party being up.

**Copy the plugin into the container / a mutable `html` volume.** Simplest manual fix. Rejected:
the image reinstalls `PLUGINS` at every boot and owns the docroot, so the copy disappears at the
next patch bump — the exact drift the current design exists to prevent.

**Install `qbehaviour_adaptiveallnothing` too.** Symmetry. Rejected: no quiz uses it (verified
against `mdl_quiz.preferredbehaviour`), and an unexercised third-party behaviour is a risk with no
benefit.
