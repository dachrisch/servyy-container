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
   `moodle-enrol_waitlist-<tag>/`, which the installer rejects with
   *"Error: the ZIP does not contain the expected folder 'waitlist'"* and the **container
   fails to start**. Repack, do not download-and-hope.
2. Bump the zip and the version together. The database pins the plugin version in
   `mdl_config_plugins`; installing newer files than the DB knows makes Moodle run that
   plugin's own upgrade steps, which is a live-DB change nobody asked for.

## `enrol_waitlist-2025072001.zip`

| | |
|---|---|
| Component | `enrol_waitlist` (enrolment method `waitlist`, plus course custom fields) |
| `version.php` | `version 2025072001`, `requires 2024083000`, release `Course Enrol Waitlist Plugin Version 4.5-a3` |
| Upstream | <https://github.com/emeneo/moodle-enrol_waitlist> tag `v4.5-a3` (`03cf4161`) |
| Why this version | `mdl_config_plugins` in Christoph's dump says `2025072001` — the exact tag, so registration is a no-op instead of a plugin upgrade |
| Used by | 21 active `waitlist` enrolment instances (2026 F2/F3/F4 Lehrgänge), 820 `user_enrolments` |
| sha256 | `0267ccb96ec6cae8349997bec899441500faf525eb3663c3608f53cca0192663` |
| Size | 125 173 B, 53 files |

Pinned in `ansible/plays/vars/default.yml` as `moodle_plugin_enrol_waitlist_zip` +
`moodle_plugin_enrol_waitlist_sha256`; the deploy asserts the checksum before compose runs
(`roles/user/tasks/moodle_plugins.yml`).

Rebuild it identically:

```bash
curl -sSL -o src.tar.gz https://codeload.github.com/emeneo/moodle-enrol_waitlist/tar.gz/refs/tags/v4.5-a3
tar xzf src.tar.gz && mv moodle-enrol_waitlist-4.5-a3 waitlist
find waitlist -type f -exec chmod 0644 {} + && find waitlist -type d -exec chmod 0755 {} +
python3 - <<'PY'
import os, zipfile
with zipfile.ZipFile("enrol_waitlist-2025072001.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for dirpath, dirnames, filenames in os.walk("waitlist"):
        dirnames.sort()
        rel = os.path.relpath(dirpath, ".")
        z.write(dirpath, rel + "/")
        for f in sorted(filenames):
            z.write(os.path.join(dirpath, f), os.path.join(rel, f))
PY
sha256sum enrol_waitlist-2025072001.zip
```

## Not vendored

`qbehaviour_adaptiveallnothing` is also referenced by the imported database, but **no quiz uses
it** (all 680 quizzes run `deferredfeedback`, `immediatefeedback` or `immediatecbm`), so it is
deliberately not installed. Moodle shows one "missing from disk" notice for it; installing it
later is the same procedure if that ever changes.
