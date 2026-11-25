#!/usr/bin/env python3
"""Pin the database variable names in the LeagueSphere app env.

`ls.env` is read by two very different consumers: the Django app (which is
moving to the MariaDB image-standard names `MYSQL_DATABASE`/`MYSQL_PASSWORD`)
and the `db` service's env_file (the entrypoint needs those same names to
create the database and user). Until the app images and the `printenv
MYSQL_PWD` infra scripts are updated, the legacy aliases must remain too.

The tests render the REAL template with mock values only: no vault, no live
host, no database and no real secret is involved.
"""

import unittest
from pathlib import Path

import jinja2

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/ls_app/templates/ls.env.j2"
)

# Fixture values. These are deliberately fake; never read the encrypted vars.
APP = dict(
    name="leaguesphere",
    db_host="fixture.db",
    db_name="fixture_db",
    db_user="fixture_user",
    db_password="fixture_password",
    moodle_url="https://moodle.example",
    moodle_wstoken="fixture-token",
    secret_key="fixture-secret",
    approval_endpoint="https://approval.example",
    approval_token="fixture-token",
    dbaccess_secret_key="fixture-key",
)

# The 2026-11-18 MARIADB_AUTO_UPGRADE outage write-up lives in this comment.
# It must survive unrelated edits to the database variable block verbatim.
WARNING = """\
# DO NOT add MARIADB_AUTO_UPGRADE here. This file is the `db` service's
# `env_file` as much as the app's, so MYSQL_HOST=<container> ends up in the
# database container's own environment; the MariaDB entrypoint's upgrade step
# shells out to the `mysql` client, which honours MYSQL_HOST and dials TCP to
# that name — while the entrypoint's temporary upgrade server is socket-only
# (`port: 0`). Result: "ERROR 2002 (HY000): Can't connect to server on
# 'leaguesphere.db' (115)" → "FATAL ERROR: Upgrade failed" → exit 1 → restart
# loop, i.e. the whole platform down. This happened on 2026-11-18 with the
# first deploy that carried the flag; see
# history/2026-11-18_ls-db-upgrade-flag-outage.md. If auto-upgrade is ever
# wanted for the high tier, give the `db` service its own env file (like
# moodle's db.env, which has no MYSQL_HOST) or set MYSQL_HOST=localhost inside
# that container — never in this shared file."""

CANONICAL = {
    "MYSQL_DATABASE": "fixture_db",
    "MYSQL_USER": "fixture_user",
    "MYSQL_PASSWORD": "fixture_password",
    "MYSQL_HOST": "fixture.db",
    "MYSQL_PORT": "3306",
}

# Kept during the transition for older app images and client scripts.
LEGACY = {
    "MYSQL_DB_NAME": "fixture_db",
    "MYSQL_PWD": "fixture_password",
}


def render(app, **context):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    variables = dict(
        app=app,
        dbeaver_dbaccess_enabled=False,
        inventory_hostname="fixture-host",
        inventory_hostname_short="fixture-host",
    )
    variables.update(context)
    return env.get_template(TEMPLATE.name).render(variables)


def assignments(rendered):
    """The rendered KEY=value pairs, with comments and blank lines ignored."""
    result = {}
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


class LsAppEnvTest(unittest.TestCase):
    def test_canonical_names_are_unconditional(self):
        # No db_root_password: this used to drop MYSQL_DATABASE/MYSQL_PASSWORD
        # entirely, so a target without the root credential never initialised
        # the image-standard database/user.
        rendered = render(dict(APP))
        values = assignments(rendered)
        for key, expected in CANONICAL.items():
            self.assertEqual(values.get(key), expected, key)
        self.assertNotIn("MYSQL_ROOT_PASSWORD", values)
        self.assertNotIn("MYSQL_BACKUP_USER", values)
        self.assertNotIn("MYSQL_BACKUP_PWD", values)

    def test_legacy_aliases_remain_for_old_consumers(self):
        for app in (dict(APP), dict(APP, db_root_password="fixture-root",
                                    db_backup_user="fixture-backup",
                                    db_backup_password="fixture-backup-pw")):
            values = assignments(render(app))
            for key, expected in LEGACY.items():
                self.assertEqual(values.get(key), expected, key)

    def test_conditional_keys_still_conditional(self):
        app = dict(APP, db_root_password="fixture-root",
                   db_backup_user="fixture-backup",
                   db_backup_password="fixture-backup-pw")
        values = assignments(render(app))
        self.assertEqual(values["MYSQL_ROOT_PASSWORD"], "fixture-root")
        self.assertEqual(values["MYSQL_BACKUP_USER"], "fixture-backup")
        self.assertEqual(values["MYSQL_BACKUP_PWD"], "fixture-backup-pw")
        for key, expected in CANONICAL.items():
            self.assertEqual(values.get(key), expected, key)

    def test_port_defaults_to_3306_and_can_be_overridden(self):
        self.assertEqual(assignments(render(dict(APP)))["MYSQL_PORT"], "3306")
        with_port = dict(APP, db_port=3307)
        self.assertEqual(assignments(render(with_port))["MYSQL_PORT"], "3307")

    def test_auto_upgrade_warning_is_verbatim(self):
        self.assertIn(WARNING, render(dict(APP)))


if __name__ == "__main__":
    unittest.main()
