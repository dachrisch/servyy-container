#!/bin/bash
# Moodle container entrypoint: run a pending upgrade before Apache starts.
#
# `moodlehq/moodle-php-apache` has no entrypoint of its own, and Moodle refuses
# to serve normally while `version.php` and the database's installed version
# disagree — the site answers "Upgrade required" instead. That is exactly what
# happens after an image bump (watchtower, or a manual `docker compose pull`),
# so the upgrade has to run here rather than be forgotten in a runbook.
#
# `--is-pending` semantics (admin/cli/upgrade.php): exit code 2 = an upgrade is
# required, 0 = nothing to do. Any other code means we could not even ask
# (missing config, DB down) — in that case stay out of the way and let the
# healthcheck/watchtower rollback handle it.
set -u

DIRROOT=/var/www/html/offd/moodle
AUTO_UPGRADE="${MOODLE_AUTO_UPGRADE:-true}"

log() { echo "[moodle-entrypoint] $*"; }

if [ -f "${DIRROOT}/config.php" ] && [ "${AUTO_UPGRADE}" = "true" ]; then
    # Moodle's CLI must run as the web server user, or the files it creates in
    # dataroot end up root-owned and Apache cannot write them afterwards.
    set +e
    su -s /bin/bash www-data -c "php ${DIRROOT}/admin/cli/upgrade.php --is-pending" >/dev/null 2>&1
    pending=$?
    set -e

    if [ "${pending}" -eq 2 ]; then
        log "pending upgrade detected (version.php != database) — running admin/cli/upgrade.php"
        if ! su -s /bin/bash www-data -c \
            "php ${DIRROOT}/admin/cli/upgrade.php --non-interactive --allow-unstable"; then
            # Fail loudly instead of serving a half-upgraded site: with
            # WATCHTOWER_HEALTH_CHECK_GATED the previous image is restored.
            log "ERROR: upgrade failed — refusing to start. See the output above."
            exit 1
        fi
        log "upgrade finished"
    else
        log "no pending upgrade (is-pending exit=${pending})"
    fi
fi

exec "$@"
