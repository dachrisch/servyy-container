# Vendored Moodle plugins

The `erseco/alpine-moodle` image keeps its docroot immutable and installs every third-party
plugin **at container boot** from `PLUGINS=` in `app.env` (rendered from
[`moodle.app.env.j2`](../../ansible/plays/roles/docker_service/templates/moodle.app.env.j2)).
The archives therefore live here, in git, and are bind-mounted read-only into the container
(`./plugins:/opt/moodle-plugins`), so a rebuild needs nothing external — no moodle.org
download at boot, no "the plugin disappeared after an image bump".

`PLUGINS` entries are `type_name=url`; the image's `015-copy-plugins.sh` does
`curl "$url"` → `unzip` → `mv "$plugin_subdir" <docroot>/<type>/<subdir>`. Two consequences:

1. The zip **must** contain a single top-level directory whose name is exactly the plugin's
   subdir (`waitlist/` for `enrol_waitlist`). GitHub's own archive root is
   `moodle-enrol_waitlist-<tag-or-sha>/`, which the installer rejects with
   *"Error: the ZIP does not contain the expected folder 'waitlist'"* and the **container
   fails to start**. Repack, do not download-and-hope.
2. A zip **newer** than the database's `mdl_config_plugins` row makes Moodle run that plugin's
   own upgrade steps on the next boot. That is fine only when `db/upgrade.php` has no step for
   the range and `db/install.xml` is unchanged (see the bump procedure below) — otherwise it is
   an unrequested live-DB change.

## `enrol_waitlist-2026051200.zip`

| | |
|---|---|
| Component | `enrol_waitlist` (enrolment method `waitlist`, plus course custom fields) |
| `version.php` | `version 2026051200`, `requires 2024083000`, release `Course Enrol Waitlist Plugin Version 4.5-b` |
| Upstream | <https://github.com/emeneo/moodle-enrol_waitlist> commit `1bfd5b5a43` (2026-05-12, "Security fixes") |
| Why a commit, not a tag | The tag `v4.5b` contains `version 2025072000` — *older* than the `v4.5-a3` we replaced. Master's HEAD is the only source of `2026051200`, so it is pinned by commit sha |
| Why this version | 4.5-b is the remediation of upstream issue #16: `enroluser.php`/`users.php`/`unenrol.php` had their `require_capability()` calls commented out, `profile/assign.php` lacked CSRF protection and `faculty.php` was an unauthenticated JSON endpoint. `2025072001` (4.5-a3) has all five holes |
| Upgrade cost | `db/install.xml` byte-identical, no `xmldb_enrol_waitlist_upgrade()` step between 2025072001 and 2026051200 → version bookkeeping only |
| Used by | 52 `waitlist` enrolment instances (14 active 2026 F2/F3/F4 Lehrgänge), 820 `user_enrolments` |
| Capability note | The new checks require `enrol/waitlist:manage`/`:unenrol` (editingteacher, manager archetypes). OFFD's custom role `landesverband` already holds both at system context, verified in `mdl_role_capabilities` before deploying |
| sha256 | `2266fa07d360414efc1af74e592f988a09e14af4af60def5063752a548a0c090` |
| Size | 125 727 B, 53 files (74 zip entries) |

Pinned in `ansible/plays/vars/default.yml` as `moodle_plugin_enrol_waitlist_zip` +
`moodle_plugin_enrol_waitlist_sha256`; the deploy asserts the checksum before compose runs
(`roles/user/tasks/moodle_plugins.yml`).

Recreate it identically:

```bash
SHA=1bfd5b5a43eab836070af1e00cc0c64988ba6525   # "Security fixes", version.php 2026051200
curl -sSL -o src.tar.gz https://codeload.github.com/emeneo/moodle-enrol_waitlist/tar.gz/$SHA
tar xzf src.tar.gz && mv moodle-enrol_waitlist-$SHA waitlist
find waitlist -type f -exec chmod 0644 {} + && find waitlist -type d -exec chmod 0755 {} +
python3 - <<'PY'
import os, zipfile
with zipfile.ZipFile("enrol_waitlist-2026051200.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for dirpath, dirnames, filenames in os.walk("waitlist"):
        dirnames.sort()
        rel = os.path.relpath(dirpath, ".")
        z.write(dirpath, rel + "/")
        for f in sorted(filenames):
            z.write(os.path.join(dirpath, f), os.path.join(rel, f))
PY
sha256sum enrol_waitlist-2026051200.zip   # must equal the hash above
```

Marketplace's own download endpoint (`moodle.org/plugins/738/...`) 404s from both this
machine and the server, which is why the archive is rebuilt from GitHub instead.

## Bumping it again

1. Read the upstream `version.php`, `db/upgrade.php` and `db/install.xml` of the target commit
   **before** touching the repo. If `upgrade.php` has a step for the version range or
   `install.xml` changed, the bump is a schema migration: rehearse it on `servyy-test.lxd` with
   a real dump, not on production.
2. Vendor it from a **commit sha** (tags in this repo have pointed at the wrong version), name
   the file `enrol_waitlist-<version>.zip`, keep the `waitlist/` root.
3. Update `moodle_plugin_enrol_waitlist_zip` + `..._sha256`, the two molecule fixtures
   (`roles/docker_service/molecule/default/{converge,verify}.yml`), this table and
   [`../AGENTS.md`](../AGENTS.md) in the same change.
4. Deploy with `--tags user.docker.repo,user.docker.moodle`; the boot log must show
   `Successfully installed enrol_waitlist`, the container must be healthy with 0 restarts, and
   `mdl_config_plugins` must show the new version with `upgrade.php --is-pending` at 0.

## Not vendored

`qbehaviour_adaptiveallnothing` is also referenced by the imported database, but **no quiz uses
it** (all 680 quizzes run `deferredfeedback`, `immediatefeedback` or `immediatecbm`), so it is
deliberately not installed. Moodle shows one "missing from disk" notice for it; installing it
later is the same procedure if that ever changes.
