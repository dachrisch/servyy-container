#!/usr/bin/env bash
# One-time wwwroot rewrite for teacher-entered absolute links.
#
# $CFG->wwwroot comes from SITE_URL (config.php, written by the image), but the
# source site lived at https://offd.de/offd/moodle and teachers pasted absolute
# links into course content. Moodle cannot fix those; this script does.
#
#   moodle/scripts/wwwroot-replace.sh https://offd.de/offd/moodle https://offd.de
#   moodle/scripts/wwwroot-replace.sh https://offd.de/offd/moodle https://m.leaguesphere.app
#
# Only the columns that hold *live content* are touched — measured on the real
# dump on 2026-10-28 (~134 rows): question text/answers, book chapters, page
# content, URL activity targets. Message history, autosave drafts and config logs
# contain ~40 k rows of the same string and are deliberately left alone.
#
# `--include-attempts` also rewrites mdl_question_attempts.questionsummary (the
# frozen rendering of each attempt, ~310 rows). Off by default: it is review
# history, not content, and changing it is only cosmetic.
#
# Idempotent: a second run reports 0 rows before and after.

set -euo pipefail

OLD="${1:-}"
NEW="${2:-}"
INCLUDE_ATTEMPTS=false
for arg in "$@"; do [[ "$arg" == "--include-attempts" ]] && INCLUDE_ATTEMPTS=true; done

fail() { printf '\033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
[[ -n "$OLD" && -n "$NEW" ]] || fail "usage: $(basename "$0") <old-prefix> <new-prefix> [--include-attempts]"
[[ "$OLD" != "$NEW" ]] || fail "old and new prefix are identical"
command -v docker >/dev/null || fail "docker not found — run this on servy"

# Single quotes are escaped for SQL; both arguments are URLs, never user input.
sql_quote() { printf "%s" "${1//\'/\'\'}"; }
QOLD="$(sql_quote "$OLD")"
QNEW="$(sql_quote "$NEW")"

db() {
  docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" --batch --skip-column-names moodle'
}

columns=(question.questiontext question_answers.answer book_chapters.content url.externalurl page.content)
[[ "$INCLUDE_ATTEMPTS" == true ]] && columns+=(question_attempts.questionsummary)

count_sql() {
  local first=1 out=""
  for c in "${columns[@]}"; do
    local t="${c%%.*}" col="${c##*.}"
    [[ $first -eq 1 ]] || out+=" + "
    out+="(SELECT COUNT(*) FROM mdl_$t WHERE $col LIKE '%$QOLD%')"
    first=0
  done
  printf 'SELECT %s;' "$out"
}

BEFORE="$(db <<<"$(count_sql)")"
printf 'rows containing %s: %s\n' "$OLD" "$BEFORE"
if [[ "$BEFORE" == "0" ]]; then
  printf '\033[33mnothing to replace — already done\033[0m\n'
  exit 0
fi

{
  for c in "${columns[@]}"; do
    t="${c%%.*}"; col="${c##*.}"
    printf "UPDATE mdl_%s SET %s = REPLACE(%s, '%s', '%s');\n" "$t" "$col" "$col" "$QOLD" "$QNEW"
  done
} | db

AFTER="$(db <<<"$(count_sql)")"
printf 'rows remaining: %s\n' "$AFTER"
[[ "$AFTER" == "0" ]] || fail "still $AFTER rows containing $OLD"
printf '\033[32mok\033[0m rewritten to %s\n' "$NEW"
