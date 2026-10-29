#!/bin/bash
# Contract tests for the Docker edge filter (tasks/firewall.yml).
#
# Docker writes its own FORWARD rules and ignores ufw, so a `ports:` entry in any compose file
# is internet-facing unless something blocks it. The filter is a HOST-EDGE chain hooked from
# DOCKER-USER: allow the edge ports in on the public interface, drop everything else. These
# checks keep it from silently becoming a no-op — the failure mode is a rule set that renders
# but filters nothing.
#
# Usage: bash ansible/plays/roles/system/tests/test_docker_edge_filter.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE="$(dirname "${HERE}")"
SCRIPT_TPL="${ROLE}/templates/docker-user-firewall.sh.j2"
UNIT_TPL="${ROLE}/templates/docker-user-firewall.service.j2"

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
        PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"
    else
        FAIL=$((FAIL + 1)); printf '  FAIL %s\n         expected: %s\n         actual:   %s\n' "$1" "$3" "$2"
    fi
}

render() { # $1=template $2=output $3=ports json
    python3 - "$1" "$2" "$3" <<'PY'
import json, sys
import jinja2

tpl, out, ports = sys.argv[1:4]
with open(tpl) as fh:
    source = fh.read()
ctx = {"edge_allowed_tcp_ports": json.loads(ports)}
env = jinja2.Environment(autoescape=False, keep_trailing_newline=True)
with open(out, "w") as fh:
    fh.write(env.from_string(source).render(**ctx))
PY
}

SCRIPT="${WORK}/docker-user-firewall.sh"
render "${SCRIPT_TPL}" "${SCRIPT}" '[22, 80, 443]'
UNIT="${WORK}/docker-user-firewall.service"
render "${UNIT_TPL}" "${UNIT}" '[]'

echo "== script =="
bash -n "${SCRIPT}" && check "script parses" "ok" "ok"

check "own chain, so foreign DOCKER-USER rules are never flushed" \
    "$(grep -c '^CHAIN="HOST-EDGE"' "${SCRIPT}")" "1"
check "lets established/return traffic through" \
    "$(grep -c 'conntrack --ctstate RELATED,ESTABLISHED -j RETURN' "${SCRIPT}")" "1"
check "allows exactly the edge ports" \
    "$(grep -c -- '-p tcp -m multiport --dports "${PORTS}" -j RETURN' "${SCRIPT}")" "1"
check "drops the rest, and as the last rule" \
    "$(grep -c -- '-i "${IFACE}" -j DROP' "${SCRIPT}")" "1"
check "hooks the chain into DOCKER-USER" \
    "$(grep -c -- '-I DOCKER-USER 1 -j "${CHAIN}"' "${SCRIPT}")" "1"
check "filters only the public interface (container traffic untouched)" \
    "$(grep -c -- '-i "${IFACE}"' "${SCRIPT}")" "3"
check "refuses to run without a default route" \
    "$(grep -c 'no default route found' "${SCRIPT}")" "1"
check "fails loudly when DOCKER-USER is missing" \
    "$(grep -c 'DOCKER-USER chain is missing' "${SCRIPT}")" "1"
check "covers IPv6 as well" \
    "$(grep -c 'ip6tables -n -L DOCKER-USER' "${SCRIPT}")" "1"

CUSTOM="${WORK}/custom.sh"
render "${SCRIPT_TPL}" "${CUSTOM}" '[22, 443, 8080]'
check "ports are configurable" \
    "$(grep -c '^PORTS="22,443,8080"' "${CUSTOM}")" "1"

echo "== unit =="
check "runs after docker (DOCKER-USER exists only then)" \
    "$(grep -c '^After=docker.service' "${UNIT}")" "1"
check "re-runs on daemon restarts (chain is recreated)" \
    "$(grep -c '^Requires=docker.service' "${UNIT}")" "1"
check "oneshot with a stable state" \
    "$(grep -c '^RemainAfterExit=yes' "${UNIT}")" "1"

echo
if [[ "${FAIL}" -gt 0 ]]; then
    echo "FAILED: ${FAIL} check(s) failed, ${PASS} passed"
    exit 1
fi
echo "PASSED: ${PASS} checks"
