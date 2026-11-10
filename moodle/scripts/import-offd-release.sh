#!/usr/bin/env bash
# Land a verified OFFD export on the live instance: content + database, in one
# pass, with the wwwroot rewrite at the end.
#
#   moodle/scripts/verify-offd-export.sh moodledata.tar.gz dump.sql.gz   # must PASS
#   moodle/scripts/import-offd-release.sh moodledata.tar.gz dump.sql.gz
#
# Options:
#   --yes                 do not ask for confirmation
#   --dry-run             print what would happen (paths, DB, top level, counts)
#                         and exit without touching anything; implies --yes
#   --target-url URL      rewrite teacher-entered links to this URL
#                         (default: the instance's current SITE_URL from app.env)
#   --include-attempts    also rewrite mdl_question_attempts.questionsummary
#   --skip-fresh-dump     do not insist on a fresh logical dump as rollback point
#
# Order matters and is deliberate:
#   1. a *fresh* logical dump of the current database becomes the on-disk rollback
#      point (restic already has hourly snapshots; this one is same-minute);
#   2. the app container is stopped, the DB container keeps running;
#   3. content is extracted over the dataroot — filedir is content-addressed and
#      never rewritten in place, so a first export's files cannot be corrupted by
#      a second one; files that no longer exist stay behind as orphans (harmless,
#      and the nightly file snapshot covers them either way);
#   4. the database is dropped and re-imported from the dump (~8 min for 1.6 GB);
#   5. the app starts and the image runs admin/cli/upgrade.php itself because the
#      dump is 4.5.12 while the image is 4.5.15 — the script waits for it;
#   6. teacher-entered links are rewritten to the target URL, caches purged;
#   7. counts are printed for the runbook's verification table.
#
# This does NOT touch DNS, SITE_URL or the Traefik router: the site keeps serving
# whatever host it served before, which is what makes it safe to run before the
# cutover. Cutover is an inventory change + deploy (docs/plans/
# 2026-11-13-moodle-final-drop-release.md).

set -euo pipefail

ARCHIVE="${1:-}"
DUMP="${2:-}"
shift 2 2>/dev/null || true

ASSUME_YES=false
DRY_RUN=false
TARGET_URL=""
INCLUDE_ATTEMPTS=""
SKIP_FRESH_DUMP=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES=true ;;
    --dry-run) DRY_RUN=true; ASSUME_YES=true ;;
    --target-url) TARGET_URL="${2:-}"; shift ;;
    --include-attempts) INCLUDE_ATTEMPTS="--include-attempts" ;;
    --skip-fresh-dump) SKIP_FRESH_DUMP=true ;;
    *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$SERVICE_DIR/scripts"
fail() { printf '\033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m ok \033[0m %s\n' "$*"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[[ -n "$ARCHIVE" && -n "$DUMP" ]] || fail "usage: $(basename "$0") <moodledata.tar.gz> <dump.sql.gz> [--yes] [--target-url URL]"
[[ -f "$ARCHIVE" && -f "$DUMP" ]] || fail "archive or dump not found"
command -v docker >/dev/null || fail "docker not found — run this on servy"

# The rendered .env / db.env are 0600 and root-owned on the host, so a cda-run
# script may not be able to read them. Prefer the running containers: the
# compose interpolation vars and the DB env are already resolved there.
DATA_ROOT="$(sed -n 's/^MOODLE_DATA_ROOT=//p' "$SERVICE_DIR/.env" 2>/dev/null || true)"
if [[ -z "$DATA_ROOT" ]]; then
  DATA_ROOT="$(dirname "$(docker inspect moodle.moodle \
    --format '{{range .Mounts}}{{if eq .Destination "/var/www/moodledata"}}{{.Source}}{{end}}{{end}}')")"
fi
SITE_URL="$(docker inspect moodle.moodle --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | sed -n 's/^SITE_URL=//p')"
# `data/` is root:root 0750 (roles/user/tasks/moodle_data_dirs.yml), so every
# test below the data root needs sudo — a plain `-d` silently answers "no" here.
[[ -n "$DATA_ROOT" ]] && sudo test -d "$DATA_ROOT/moodledata" \
  || fail "cannot resolve the moodledata root (checked .env and the moodle.moodle mounts)"
[[ -n "$TARGET_URL" ]] || TARGET_URL="$SITE_URL"
DB_NAME="$(docker exec moodle.db printenv MARIADB_DATABASE 2>/dev/null || true)"
DB_NAME="${DB_NAME:-moodle}"
OLD_PREFIX="https://offd.de/offd/moodle"
CURRENT="$DATA_ROOT/db-backup/current/moodle.sql.gz"

printf 'archive      : %s\ncontent into : %s/moodledata\ndatabase     : %s (dropped and re-imported)\nlink rewrite : %s -> %s\n' \
  "$ARCHIVE" "$DATA_ROOT" "$DB_NAME" "$OLD_PREFIX" "$TARGET_URL"

if [[ "$ASSUME_YES" != true ]]; then
  printf '\nThis REPLACES the live Moodle content and database. Type "yes" to continue: '
  read -r answer
  [[ "$answer" == "yes" ]] || fail "aborted"
fi

db_health() { docker inspect -f '{{.State.Health.Status}}' moodle.db 2>/dev/null || echo missing; }
app_health() { docker inspect -f '{{.State.Health.Status}}' moodle.moodle 2>/dev/null || echo missing; }
[[ "$(db_health)" == "healthy" ]] || fail "moodle.db is not healthy — fix that first"

if [[ "$DRY_RUN" == true ]]; then
  TOP="$(tar -tzf "$ARCHIVE" | awk 'NR==1{first=$0} END{sub(/^\.\//,"",first); split(first,a,"/"); print a[1]}')"
  printf '\n\033[36mdry run\033[0m — nothing was changed\n'
  printf 'app health     : %s\n' "$(app_health)"
  printf 'archive top    : %s\n' "$TOP"
  printf 'would extract  : -> %s/%s\n' "$DATA_ROOT" "$([[ "$TOP" == "moodledata" ]] && echo '' || echo 'moodledata')"
  printf 'would import   : %s (%s tables in the dump)\n' "$DB_NAME" "$(gzip -dc "$DUMP" | grep -c '^CREATE TABLE')"
  printf 'would rewrite  : %s -> %s\n' "$OLD_PREFIX" "$TARGET_URL"
  printf 'rollback dump  : %s %s\n' "$CURRENT" "$(sudo test -f "$CURRENT" && sudo stat -c '%s bytes, %y' "$CURRENT" || echo MISSING)"
  exit 0
fi

step "fresh rollback dump"
if [[ "$SKIP_FRESH_DUMP" != true ]]; then
  if ! sudo test -f "$CURRENT" || [[ $(( $(date +%s) - $(sudo stat -c%Y "$CURRENT") )) -gt 3600 ]]; then
    printf 'triggering moodle-dump.service (rollback point for this import)\n'
    systemctl --user start moodle-dump.service || fail "could not start moodle-dump.service"
    for _ in $(seq 1 60); do
      sudo test -f "$CURRENT" && [[ $(( $(date +%s) - $(sudo stat -c%Y "$CURRENT") )) -lt 300 ]] && break
      sleep 5
    done
  fi
  sudo test -f "$CURRENT" || fail "no fresh dump at $CURRENT"
  AGE=$(( $(date +%s) - $(sudo stat -c%Y "$CURRENT") ))
  [[ "$AGE" -lt 3600 ]] || fail "rollback dump is $((AGE / 60)) min old — refusing without a recent one"
  ROUNDTRIP="$(sudo gunzip -c "$CURRENT" | tail -c 200000 | grep -c 'Dump completed' || true)"
  ok "rollback dump $(sudo stat -c%s "$CURRENT") bytes, $((AGE / 60)) min old (gzip trailer seen: $ROUNDTRIP)"
  printf 'Reminder: also tag the restic pair, so retention cannot age this point out:\n'
  printf "  sudo bash -c 'source /etc/restic/env.moodle-db && restic tag --add pre-release latest'\n"
  printf "  sudo bash -c 'source /etc/restic/env.moodle-files && restic tag --add pre-release latest'\n"
else
  printf '\033[33mskipped on request\033[0m\n'
fi

step "extract content into the dataroot"
# `head -1` would close the pipe early; under `set -o pipefail` the SIGPIPE from
# tar then becomes a non-zero pipeline. awk reads the stream to the end instead.
TOP="$(tar -tzf "$ARCHIVE" | awk 'NR==1{first=$0} END{sub(/^\.\//,"",first); split(first,a,"/"); print a[1]}')"

# If anything fails after this point the app is restarted *only* until the
# database has been touched — serving a half-imported DB is worse than a stopped
# container, so past that line it stays down for the operator.
APP_STOPPED=false
DB_TOUCHED=false
restart_if_safe() {
  if [[ "$APP_STOPPED" == true && "$DB_TOUCHED" == false ]]; then
    ( cd "$SERVICE_DIR" && docker compose -p moodle up -d >/dev/null 2>&1 ) || true
  fi
}
trap restart_if_safe EXIT

docker stop moodle.moodle >/dev/null || fail "could not stop moodle.moodle"
APP_STOPPED=true
printf 'app container stopped; top level of archive: %s\n' "$TOP"
if [[ "$TOP" == "moodledata" ]]; then DEST="$DATA_ROOT"; else DEST="$DATA_ROOT/moodledata"; fi
sudo tar -xzf "$ARCHIVE" -C "$DEST" --no-same-owner || fail "extraction failed"
sudo chown -R 65534:65534 "$DATA_ROOT/moodledata"
sudo find "$DATA_ROOT/moodledata" -type d -exec chmod 2770 {} +
FILES="$(sudo find "$DATA_ROOT/moodledata/filedir" -type f | wc -l)"
ok "extracted, ownership 65534, $FILES files in filedir"

step "import the database (~8 min for 1.6 GB)"
# No backticks in the SQL: inside the container's `sh -c "…"` they would be command
# substitution. The name comes from db.env, so validate it instead of quoting it.
[[ "$DB_NAME" =~ ^[A-Za-z0-9_]+$ ]] || fail "unexpected database name '$DB_NAME' in db.env"
DB_TOUCHED=true
docker exec moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS '"$DB_NAME"'; CREATE DATABASE '"$DB_NAME"' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"' \
  || fail "could not recreate the database"
gunzip -c "$DUMP" | docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" "$1"' sh "$DB_NAME" \
  || fail "import failed"
TABLES="$(docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" --batch --skip-column-names "$1" -e "SHOW TABLES"' sh "$DB_NAME" | wc -l)"
ok "$TABLES tables imported"

step "start the app and wait for the automatic 4.5.12 -> 4.5.15 upgrade"
( cd "$SERVICE_DIR" && docker compose -p moodle up -d >/dev/null ) || fail "compose up failed"
APP_STOPPED=false
for _ in $(seq 1 60); do [[ "$(app_health)" == "healthy" ]] && break; sleep 5; done
[[ "$(app_health)" == "healthy" ]] || fail "moodle.moodle did not become healthy"
for _ in $(seq 1 120); do
  if docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/upgrade.php --is-pending >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/upgrade.php --is-pending >/dev/null 2>&1 \
  || fail "Moodle still reports a pending upgrade after 10 min — check docker logs moodle.moodle"
ok "app healthy, no pending upgrade"

step "rewrite teacher-entered links"
"$SCRIPTS/wwwroot-replace.sh" "$OLD_PREFIX" "$TARGET_URL" $INCLUDE_ATTEMPTS

step "purge caches and run cron"
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/purge_caches.php >/dev/null
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/cron.php >/dev/null 2>&1 || true
ok "caches purged, cron ran"

step "counts for the verification table"
docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" --batch --skip-column-names "$1"' sh "$DB_NAME" <<'SQL'
SELECT CONCAT('users_total     ', COUNT(*)) FROM mdl_user;
SELECT CONCAT('users_active    ', COUNT(*)) FROM mdl_user WHERE deleted = 0;
SELECT CONCAT('courses         ', COUNT(*)) FROM mdl_course;
SELECT CONCAT('file_rows       ', COUNT(*)) FROM mdl_files;
SELECT CONCAT('contenthashes   ', COUNT(DISTINCT contenthash)) FROM mdl_files WHERE contenthash IS NOT NULL AND contenthash <> '';
SELECT CONCAT('moodle_version  ', value) FROM mdl_config WHERE name = 'release';
SELECT CONCAT('waitlist_inst   ', COUNT(*)) FROM mdl_enrol WHERE enrol = 'waitlist' AND status = 0;
SQL
printf '\nfiledir on disk : %s\n' "$FILES"

printf '\n\033[32mimport complete\033[0m — site now serves %s\n' "$TARGET_URL"
printf 'Next: check https://%s/ , then follow the cutover section of\n' "${TARGET_URL#https://}"
printf 'docs/plans/2026-11-13-moodle-final-drop-release.md\n'
