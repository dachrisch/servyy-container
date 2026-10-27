# Moodle (OFFD / Flag Academy) — pinned release on Moodle's official PHP image.
#
# `moodlehq/moodle-php-apache` is the Moodle-maintained PHP+Apache environment
# with every extension Moodle needs, but it ships NO Moodle code: its tags are
# *PHP* versions (8.1 … 8.4), not Moodle releases. The release tarball is
# layered in here, which is Moodle's own documented production setup.
#
# The code lands at /var/www/html/offd/moodle on purpose. The live site's
# wwwroot is https://offd.de/offd/moodle, so the on-disk path mirrors the URL
# exactly and Traefik needs no rewrite rule: the two path segments are just
# directories under the document root. Do not "flatten" this.
FROM moodlehq/moodle-php-apache:8.3

ARG MOODLE_BRANCH=405
ARG MOODLE_VERSION=4.5.12

USER root

RUN set -eux; \
    mkdir -p /var/www/html/offd; \
    curl -fsSL -o /tmp/moodle.tgz \
      "https://download.moodle.org/download.php/direct/stable${MOODLE_BRANCH}/moodle-${MOODLE_VERSION}.tgz"; \
    tar -xzf /tmp/moodle.tgz -C /var/www/html/offd; \
    rm -f /tmp/moodle.tgz; \
    test -f /var/www/html/offd/moodle/version.php; \
    chown -R www-data:www-data /var/www/html/offd

# Advisory only — the release actually served is whatever this build pinned,
# and `docker exec moodle.app php .../version.php`-adjacent checks in the
# runbook compare it against the DB.
LABEL org.opencontainers.image.title="moodle-offd" \
      org.opencontainers.image.version="${MOODLE_VERSION}" \
      org.opencontainers.image.description="Moodle ${MOODLE_VERSION} (LTS) at /offd/moodle"

COPY entrypoint.sh /usr/local/bin/moodle-upgrade-guard
RUN chmod 0755 /usr/local/bin/moodle-upgrade-guard

# Deliberately NOT `USER www-data`: apache2-foreground must bind :80, and the
# guard drops to www-data for the CLI upgrade itself.
ENTRYPOINT ["/usr/local/bin/moodle-upgrade-guard"]
# CMD goes *through* the image's own entrypoint on purpose. It exports
# APACHE_DOCUMENT_ROOT (derived from a /public dir on Moodle 5.1+, plain
# /var/www/html otherwise) and renders the PHP ini from the environment.
# Bypassing it leaves the vhost with an empty DocumentRoot — every request
# answers 403 Forbidden.
CMD ["moodle-docker-php-entrypoint", "apache2-foreground"]

