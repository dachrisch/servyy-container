#!/bin/sh
# Contract tests for opencode/scripts/apk-bootstrap.sh.
#
# The 2026-11-24 codey outage was an apk DB left half-upgraded by an interrupted
# transaction: `python3-ndbm-r2` claimed a file owned by `python3-r1`, so every
# boot's `apk add` exited 1 and `set -e` turned it into a 160-restart crash loop.
# These tests pin the boot contract with a stubbed `apk`: a broken DB is repaired
# before packages are installed, and no apk failure may abort the boot.
#
# Usage: sh opencode/tests/test_apk_bootstrap.sh

set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SCRIPT="$HERE/../scripts/apk-bootstrap.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

check() { # $1=description $2=actual $3=expected
    if [ "$2" = "$3" ]; then
        PASS=$((PASS + 1))
        printf '  ok   %s\n' "$1"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %s\n         expected: %s\n         actual:   %s\n' "$1" "$3" "$2"
    fi
}

run_case() { # $1=initial state (broken|ok) $2=fix fails (0|1) -- sets RC, LOG, STATE
    : > "$WORK/log"
    printf '%s\n' "$1" > "$WORK/state"
    APK="$WORK/apk" APK_LOG="$WORK/log" APK_STATE="$WORK/state" APK_FIX_FAILS="$2" \
        sh "$SCRIPT" > "$WORK/out" 2>&1
    RC=$?
    LOG=$(cat "$WORK/log")
    STATE=$(cat "$WORK/state")
}

cat > "$WORK/apk" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$APK_LOG"
case "$1" in
    update)
        exit 0
        ;;
    fix)
        # `--force-overwrite` is the only repair we rely on.
        [ "${APK_FIX_FAILS:-0}" = "1" ] && exit 1
        printf 'ok\n' > "$APK_STATE"
        exit 0
        ;;
    add)
        if [ "$(cat "$APK_STATE")" = "broken" ]; then
            printf '1 error; 930.6 MiB in 255 packages\n'
            exit 1
        fi
        exit 0
        ;;
esac
exit 1
STUB
chmod +x "$WORK/apk"

if [ ! -f "$SCRIPT" ]; then
    printf 'FAIL: %s does not exist\n' "$SCRIPT" >&2
    exit 1
fi

echo "apk-bootstrap contract tests"

# Case 1: the exact codey state -- broken DB, repair works.
run_case broken 0
check "broken DB: boot exits 0 (no crash loop)" "$RC" "0"
check "broken DB: apk DB repaired" "$STATE" "ok"
FIX_LINE=$(printf '%s\n' "$LOG" | grep -n '^fix --force-overwrite$' | head -1 | cut -d: -f1)
ADD_LINE=$(printf '%s\n' "$LOG" | grep -n '^add ' | head -1 | cut -d: -f1)
check "broken DB: repair runs before add" "$([ -n "$FIX_LINE" ] && [ -n "$ADD_LINE" ] && [ "$FIX_LINE" -lt "$ADD_LINE" ] && echo yes || echo no)" "yes"

# Case 2: healthy DB -- repair is harmless and packages install once.
run_case ok 0
check "healthy DB: boot exits 0" "$RC" "0"
check "healthy DB: add called exactly once" "$(printf '%s\n' "$LOG" | grep -c '^add ')" "1"

# Case 3: unrepairable apk -- the service must still boot.
run_case broken 1
check "unrepairable apk: boot still exits 0" "$RC" "0"
check "unrepairable apk: warning logged" "$(grep -q 'continuing' "$WORK/out" && echo yes || echo no)" "yes"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
