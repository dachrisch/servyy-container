#!/bin/bash
# Contract tests for the auditd rules template.
#
# Lynis ACCT-9630 caught this host running auditd with an empty ruleset: the package's
# /etc/audit/rules.d contains only global settings, so `auditctl -l` was empty and nothing
# was being audited. These checks cover the shape of the rule file — a rule the kernel
# rejects makes the whole `augenrules --load` fail, so the template has to stay strict.
#
# Usage: bash ansible/plays/roles/system/tests/test_auditd_rules.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE="$(dirname "${HERE}")"
TEMPLATE="${ROLE}/templates/auditd-hardening.rules.j2"

WORK="$(mktemp -d)"
if [[ -n "${KEEP:-}" ]]; then
    echo "work dir kept at ${WORK}"
else
    trap 'rm -rf "${WORK}"' EXIT
fi

PASS=0
FAIL=0

check() { # $1=description $2=actual $3=expected
    if [[ "$2" == "$3" ]]; then
        PASS=$((PASS + 1))
        printf '  ok   %s\n' "$1"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %s\n         expected: %s\n         actual:   %s\n' "$1" "$3" "$2"
    fi
}

check_ge() { # $1=description $2=actual $3=minimum
    if [[ "$2" =~ ^[0-9]+$ ]] && (( $2 >= $3 )); then
        PASS=$((PASS + 1))
        printf '  ok   %s (%s)\n' "$1" "$2"
    else
        FAIL=$((FAIL + 1))
        printf '  FAIL %s\n         expected at least: %s\n         actual:            %s\n' "$1" "$3" "$2"
    fi
}

render() { # $1=output file $2=audit_immutable
    python3 - "${TEMPLATE}" "$1" "$2" <<'PY'
import sys
import jinja2

template_path, out_path, immutable = sys.argv[1:4]
with open(template_path) as fh:
    source = fh.read()

env = jinja2.Environment(autoescape=False, keep_trailing_newline=True)
ctx = {"hardening": {"audit_immutable": immutable == "true"}}
with open(out_path, "w") as fh:
    fh.write(env.from_string(source).render(**ctx))
PY
}

RULES="${WORK}/99-hardening.rules"
render "${RULES}" false

echo "== rule shape =="
# Anything that is not a comment, a blank line or a rule prefix would be rejected by the
# kernel and take the whole load down with it.
check "every line is a comment, blank, or a valid rule" \
    "$(grep -vcE '^[[:space:]]*(#|$|-a |-w |-e |-b |-f |--)' "${RULES}" || true)" "0"
check "global settings stay in the package's audit.rules" \
    "$(grep -cE '^-D' "${RULES}" || true)" "0"
check "no duplicate watch rules" \
    "$(grep -oE '^-w [^ ]+' "${RULES}" | sort | uniq -d | wc -l)" "0"

echo "== coverage =="
for key in identity privilege auth cron docker systemd audit modules time-change system-locale mounts user-modify group-modify; do
    check_ge "watches or keys the '${key}' class" \
        "$(grep -cE "( -k ${key}\$)" "${RULES}" || true)" 1
done

check_ge "privileged binaries are audited for execution" \
    "$(grep -cE '^-w /usr/(s?bin|sbin)/[a-z]+ -p x ' "${RULES}" || true)" 5

echo "== immutability is opt-in =="
check "no -e 2 by default" "$(grep -cE '^-e 2$' "${RULES}" || true)" "0"
render "${WORK}/immutable.rules" true
check "renders -e 2 when audit_immutable is true" \
    "$(grep -cE '^-e 2$' "${WORK}/immutable.rules" || true)" "1"
check "-e 2 is the last rule" \
    "$(grep -vE '^[[:space:]]*(#|$)' "${WORK}/immutable.rules" | tail -1)" "-e 2"

echo
if [[ "${FAIL}" -gt 0 ]]; then
    echo "FAILED: ${FAIL} check(s) failed, ${PASS} passed"
    exit 1
fi
echo "PASSED: ${PASS} checks"
