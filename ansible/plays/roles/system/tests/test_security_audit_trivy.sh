#!/bin/bash
# Tests for the trivy step of the security audit script.
#
# Renders ansible/plays/roles/system/templates/security-audit.sh.j2 with every tool except
# trivy disabled, runs it against stub docker/trivy binaries, and asserts on the files it
# produces (trivy-results.json, trivy-summary.txt, SUMMARY.md).
#
# Covers the failure mode found on servy.lehel.xyz on 2026-10-28: `trivy image` cannot read
# images whose layer blobs are gone from containerd's content store (`file blobs/sha256/...
# not found in tar`), and the script used to record those as an empty result.
#
# Usage: bash ansible/plays/roles/system/tests/test_security_audit_trivy.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE="$(dirname "${HERE}")"
TEMPLATE="${ROLE}/templates/security-audit.sh.j2"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

BIN="${WORK}/bin"
LOGS="${WORK}/logs"
CALLS="${WORK}/calls"
OPT="${WORK}/opt"
mkdir -p "${BIN}" "${LOGS}" "${CALLS}" "${OPT}"

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

# ---------------------------------------------------------------- stubs -----
# docker ps            -> the three fixture images
# docker ps --filter   -> a synthetic container id derived from the image name
# docker export        -> a "rootfs tar" whose only content is that container id, so the
#                         trivy stub can tell which image is being scanned
cat > "${BIN}/docker" <<'STUB'
#!/bin/bash
echo "docker $*" >> "${STUB_CALLS}/docker.log"
if [[ "${1:-}" == "ps" ]]; then
    for a in "$@"; do
        case "${a}" in
            -q) exit 0 ;;
            ancestor=*) echo "cid-${a#ancestor=}"; exit 0 ;;
        esac
    done
    printf '%s\n' 'good:latest' 'broken:latest' 'unscannable:latest'
    exit 0
fi
if [[ "${1:-}" == "export" ]]; then
    out=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -o) out="$2"; shift 2 ;;
            *) cid="$1"; shift ;;
        esac
    done
    echo "${cid}" > "${out}"
    echo "${cid}" >> "${STUB_CALLS}/exports.log"
    exit 0
fi
exit 0
STUB
chmod +x "${BIN}/docker"

# trivy image  -> good:latest succeeds; the other two fail the way the containerd image
#                 store fails when layer blobs are missing
# trivy rootfs -> only succeeds for the image whose export says cid-broken:latest
cat > "${BIN}/trivy" <<'STUB'
#!/bin/bash
echo "trivy $*" >> "${STUB_CALLS}/trivy.log"
findings() {
    cat <<'JSON'
{"SchemaVersion": 2, "Results": [{"Target": "stub (alpine 3.22)", "Vulnerabilities": [{"VulnerabilityID": "CVE-2026-9999", "Severity": "CRITICAL"}]}]}
JSON
}
cmd="${1:-}"
target="${!#}"
case "${cmd}" in
    image)
        case "${target}" in
            good:latest) findings; exit 0 ;;
            *) echo "FATAL image scan error: file blobs/sha256/deadbeef not found in tar" >&2; exit 1 ;;
        esac ;;
    rootfs)
        if head -c 200 "${target}" | grep -q 'cid-broken:latest'; then
            findings
            exit 0
        fi
        echo "FATAL rootfs scan error: unable to read ${target}" >&2
        exit 1 ;;
    config)
        echo '{}'
        exit 0 ;;
esac
exit 0
STUB
chmod +x "${BIN}/trivy"

# --------------------------------------------------------------- render -----
python3 - "${TEMPLATE}" "${WORK}/audit.sh" "${LOGS}" "${OPT}" <<'PY'
import sys
import jinja2

template_path, out_path, log_dir, script_dir = sys.argv[1:5]
with open(template_path) as fh:
    source = fh.read()

ctx = {
    "security_audit": {
        "log_dir": log_dir,
        "script_dir": script_dir,
        "tools": {
            "lynis": False,
            "docker_bench": False,
            "trivy": True,
            "nmap": False,
            "testssl": False,
            "humble": False,
            "nuclei": False,
        },
    }
}
env = jinja2.Environment(autoescape=False, keep_trailing_newline=True)
# Ansible builtin filter, not part of plain Jinja2.
env.filters["ternary"] = lambda value, true_val, false_val: true_val if value else false_val
rendered = env.from_string(source).render(**ctx)
with open(out_path, "w") as fh:
    fh.write(rendered)
PY
chmod +x "${WORK}/audit.sh"

STUB_CALLS="${CALLS}" PATH="${BIN}:${PATH}" bash "${WORK}/audit.sh" > "${WORK}/run.log" 2>&1
RUN_RC=$?

RESULTS="${LOGS}/$(date +%Y-%m-%d)/trivy-results.json"
SUMMARY="${LOGS}/$(date +%Y-%m-%d)/SUMMARY.md"
TOOL_LOG="${LOGS}/$(date +%Y-%m-%d)/trivy.log"

# -------------------------------------------------------------- helpers -----
probe() { # $1=query, remaining args passed through
    python3 - "${RESULTS}" "$@" <<'PY'
import json
import sys

path, query, *rest = sys.argv[1:]
rows = json.load(open(path))

def row(target):
    for entry in rows:
        if entry.get("target") == target:
            return entry
    return None

def criticals(entry):
    result = entry.get("result") or {}
    return sum(
        1
        for section in (result.get("Results") or [])
        for vuln in (section.get("Vulnerabilities") or [])
        if vuln.get("Severity") == "CRITICAL"
    )

if query == "valid":
    print("yes")
elif query == "scanner":          # which scanner succeeded for an image
    entry = row(rest[0])
    print(entry.get("scanner", "missing") if entry else "no-row")
elif query == "kind":             # "result" (scanned) or "error" (not scanned)
    entry = row(rest[0])
    if entry is None:
        print("no-row")
    elif "error" in entry:
        print("error")
    elif "result" in entry:
        print("result")
    else:
        print("neither")
elif query == "criticals":
    entry = row(rest[0])
    print(criticals(entry) if entry else "no-row")
elif query == "empty-results":    # rows carrying a result that scanned nothing
    print(sum(1 for e in rows if e.get("result") in ({}, None) and "error" not in e))
PY
}

file_probe() { # $1=file $2=grep pattern -> count (0 when the file is absent)
    if [[ -f "$1" ]]; then
        grep -c -- "$2" "$1" 2>/dev/null || true
    else
        echo 0
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

# ---------------------------------------------------------------- checks ----
echo "== rendered script exit code =="
check "audit script runs" "${RUN_RC}" "0"

echo "== trivy-results.json =="
check "results file is valid JSON" "$(probe valid)" "yes"
check "healthy image scanned via the image source" "$(probe scanner good:latest)" "image"
check "healthy image keeps its finding" "$(probe criticals good:latest)" "1"
check "healthy image is not exported" "$(file_probe "${CALLS}/exports.log" 'anything')" "0"

echo "== rootfs fallback =="
check "unexportable image falls back to a rootfs scan" "$(probe scanner broken:latest)" "rootfs"
check "fallback keeps the finding" "$(probe criticals broken:latest)" "1"
check "fallback exports the failing image only" "$(file_probe "${CALLS}/exports.log" 'cid-broken:latest')" "1"
check "fallback export is cleaned up" "$(ls "${LOGS}"/"$(date +%Y-%m-%d)" | grep -c '\.trivy-rootfs' || true)" "0"

echo "== unscannable images =="
check "successful scans are recorded as results" "$(probe kind good:latest)" "result"
check "unscannable image is recorded as an error" "$(probe kind unscannable:latest)" "error"
check "no row claims an empty result" "$(probe empty-results)" "0"
check_ge "trivy's failure reaches the tool log" "$(file_probe "${TOOL_LOG}" 'FATAL')" 1

echo
if [[ "${FAIL}" -gt 0 ]]; then
    echo "FAILED: ${FAIL} check(s) failed, ${PASS} passed"
    echo "--- script output ---"
    sed 's/^/  /' "${WORK}/run.log" | tail -40
    exit 1
fi
echo "PASSED: ${PASS} checks"
