# Store-agnostic Trivy scanning + honest failure reporting

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the monthly security audit scan every running container image even when the
docker daemon cannot export it, and make an unscannable image show up as an error instead of
an empty (i.e. fake-clean) result.

**Architecture:** `run_trivy()` keeps the fast path (`trivy image`, which reads the local
content store via `docker save`) and adds a fallback that scans the container's merged
filesystem (`docker export` → `trivy rootfs`), which reads through the runtime's snapshot and
is therefore independent of the storage driver, the image store backend, and whether the layer
blobs still exist. Every row in `trivy-results.json` becomes one of two shapes — `result`
(scanned) or `error` (not scanned) — and image counts are published to `trivy-summary.txt` so
`generate_summary()` can report coverage in `SUMMARY.md`.

**Tech Stack:** bash (template `security-audit.sh.j2`), Jinja2, Ansible (`system` role),
trivy 0.74, docker 28 with the containerd image store, systemd timer.

**Context (why):** On `servy.lehel.xyz` the last audit (`/var/log/security-audit/2026-10-09`)
recorded `{}` for 14 of 47 running images. `trivy image` failed with
`unable to open: … file blobs/sha256/… not found in tar` because the layer blobs are gone from
containerd's content store while the image records and unpacked snapshots survive; the script
discarded stderr (`2>/dev/null`) and wrote `{}`, which every consumer reads as "no findings".
See `history/2026-10-28_security-audit-trivy-empty-results.md`.

---

## Task 1: Test harness + fast-path behaviour

**Files:**
- Create: `ansible/plays/roles/system/tests/test_security_audit_trivy.sh`

**Step 1: Write the failing test**

A self-contained bash test that (a) renders the real template with jinja2 into a temp dir,
(b) puts stub `docker`/`trivy`/`nmap`/`lynis`/`nuclei` binaries on `PATH`, (c) runs the
rendered script with every tool except trivy disabled, and (d) asserts on the produced
`trivy-results.json`.

Stub contract used by the test:

| image | `trivy image` | `docker export` | `trivy rootfs` |
|---|---|---|---|
| `good:latest` | exit 0 + findings JSON | not called | not called |
| `broken:latest` | exit 1 + `FATAL … not found in tar` | 1 KB fake tar | exit 0 + findings JSON |
| `unscannable:latest` | exit 1 | 1 KB fake tar | exit 1 |

Assertions for this task (fast path only):

```bash
assert_json_valid "${results}"
assert_eq "image" "$(row_scanner good:latest)"       # scanner recorded as "image"
assert_eq "1"     "$(critical_count good:latest)"    # finding preserved
assert_eq "0"     "$(export_calls)"                  # no fallback for a healthy image
```

**Step 2: Run it, watch it fail**

```bash
bash ansible/plays/roles/system/tests/test_security_audit_trivy.sh
# expected: FAIL — no "scanner" key in trivy-results.json
```

**Step 3: Implement the minimum**

In `security-audit.sh.j2` add to `run_trivy()`: a `json_ok()` helper, a
`scan_image()` helper wrapping `trivy image`, and a row writer that adds
`"scanner": "image"` to successful rows.

**Step 4: Run the test again → PASS**

**Step 5: Commit**

```bash
git add ansible/plays/roles/system/templates/security-audit.sh.j2 \
        ansible/plays/roles/system/tests/test_security_audit_trivy.sh
git commit -m "test(security-audit): harness for trivy image scanning"
```

---

## Task 2: Rootfs fallback when the daemon cannot export the image

**Files:**
- Modify: `ansible/plays/roles/system/templates/security-audit.sh.j2` (`run_trivy`)

**Step 1: Write the failing test** — extend the harness with:

```bash
assert_eq "rootfs" "$(row_scanner broken:latest)"
assert_eq "1"      "$(critical_count broken:latest)"
assert_eq "broken:latest" "$(exported_images)"     # fallback did run, for that image only
```

**Step 2: Run it, watch it fail** — `broken:latest` currently has no row at all.

**Step 3: Implement the minimum**

```bash
scan_rootfs() {                    # $1=image $2=result-json $3=temp-tar
    local cid
    cid="$(docker ps --filter "ancestor=$1" --format '{{.ID}}' | head -1)"
    [[ -n "${cid}" ]] || return 1
    docker export "${cid}" -o "$3" || return 1
    trivy rootfs --scanners vuln --format json --severity HIGH,CRITICAL "$3" > "$2"
}
```

Fall back to it only after `trivy image` fails or produces unparseable JSON. Note
`trivy rootfs -` does **not** accept stdin (verified: `lstat -: no such file or directory`),
so the export must go to a temp file, deleted after each image.

**Step 4: Run the test → PASS**

**Step 5: Commit** — `feat(security-audit): fall back to a rootfs scan when the image cannot be exported`

---

## Task 3: Never report an unscanned image as clean

**Files:**
- Modify: `ansible/plays/roles/system/templates/security-audit.sh.j2` (`run_trivy`)

**Step 1: Write the failing test**

```bash
assert_eq "error" "$(row_kind unscannable:latest)"   # row has "error", not "result"
assert_eq "0"     "$(empty_result_rows)"             # no "result": {} anywhere
assert_log_contains "unscannable:latest"             # failure is visible in the tool log
```

**Step 2: Run it, watch it fail** — `unscannable:latest` currently gets `"result": {}`.

**Step 3: Implement the minimum**

Rows become `{"target": …, "scanner": …, "result": …}` on success and
`{"target": …, "error": "scan failed, see trivy.log"}` on failure; drop every
`2>/dev/null` in the scan path so trivy's `FATAL` line reaches `trivy.log` via
`run_tool`'s `tee`. `grep -c '"Severity": "CRITICAL"'` must keep working (it does — the
success shape is unchanged).

**Step 4: Run the test → PASS**

**Step 5: Commit** — `fix(security-audit): record unscannable images as errors, not empty results`

---

## Task 4: Report coverage in SUMMARY.md

**Files:**
- Modify: `ansible/plays/roles/system/templates/security-audit.sh.j2` (`run_trivy`, `generate_summary`)

**Step 1: Write the failing test**

```bash
assert_eq "scanned=2"        "$(grep '^scanned=' "${log_dir}/trivy-summary.txt")"
assert_eq "failed=1"         "$(grep '^failed='  "${log_dir}/trivy-summary.txt")"
assert_summary_contains "Images scanned: 2/3"
assert_summary_contains "unscannable:latest"
```

**Step 2: Run it, watch it fail** — `trivy-summary.txt` does not exist.

**Step 3: Implement the minimum**

`run_trivy` writes `trivy-summary.txt` (`scanned=`, `failed=`, one `failed_target=` per
failure). Why a file: `run_tool` runs the function inside `"$@" 2>&1 | tee …`, a subshell, so
shell variables set inside `run_trivy` never reach `generate_summary`.
`generate_summary` appends a `Container images scanned: X/Y` line plus a `## Scan Failures`
section when `failed > 0`.

**Step 4: Run the test → PASS**

**Step 5: Commit** — `feat(security-audit): report trivy scan coverage in SUMMARY.md`

---

## Task 5: Verify against the real host

**Files:** none

**Step 1:** Lint and syntax check

```bash
cd ansible && yamllint -c ../.yamllint.yml . && ansible-playbook servyy.yml --syntax-check -i testing
```

**Step 2:** Deploy to servy and run the audit service

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags system.security_audit
ssh servy.lehel.xyz "sudo systemctl start security-audit.service"
```

**Step 3:** Assert coverage — replaces the previous 33/47:

```bash
D=/var/log/security-audit/$(date +%F)
python3 - <<'PY'   # run on the host
import json; d=json.load(open("/var/log/security-audit/%s/trivy-results.json" % __import__("datetime").date.today()))
print(len(d), "rows", sum(1 for e in d if "result" in e), "scanned", sum(1 for e in d if "error" in e), "failed")
PY
```

Expected: 47 rows, `failed=0`, and `scanner` = `rootfs` for the images that failed before.

**Step 4:** Commit any deployment-driven follow-ups; record results in the history entry.

---

## Task 6: History entry

**Files:**
- Create: `history/2026-10-28_security-audit-trivy-empty-results.md`

Document: the symptom (14/47 images silently unscanned since the report became readable),
the three pieces of evidence (874 KB `docker save` tar, `ctr content get` → not found,
dangling `gc.ref.content.l.*` labels), why storage is not the fix, the fallback + error-row
change, and the open question of what removes blobs referenced by live images (suspected:
daily `docker system prune -a` + Watchtower churn sharing the containerd store).

Commit: `docs(history): record the trivy empty-result root cause and the rootfs fallback`
