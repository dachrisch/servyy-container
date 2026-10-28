# Security audit: 14 of 47 images were silently unscanned

**Date:** 2026-10-28
**Status:** ✅ Verified on `servy.lehel.xyz` — 46/46 images scanned, 0 failures
**Relates to:** `2026-10-08_security-audit-tool-fixes.md`, `2026-10-27_servy-disk-reclaim-and-job-search-retirement.md`

## Context

While checking the latest security scan, 14 of the 47 container images in
`/var/log/security-audit/2026-10-09/trivy-results.json` turned out to carry `"result": {}`
— no findings, no error, indistinguishable from an image that scanned clean:

```
bumblecode/ibs:latest          dachrisch/job-search-crawler:latest   leaguesphere/frontend:demo
emarcs/nginx-git:latest        gcr.io/cadvisor/cadvisor:latest       leaguesphere/frontend:latest
grafana/promtail:latest        leaguesphere/backend:demo             leaguesphere/frontend:staging
leaguesphere/backend:latest    leaguesphere/backend:staging          mcuadros/ofelia:latest
prom/pushgateway:v1.6.2        traefik:3.6.1
```

The 33 images that did scan all have real `Results` sections, so their counts stand; only
these 14 rows were unknown. That is 30% of the fleet absent from the report.

## Root cause

`run_trivy()` scans each image with `trivy image <ref>`, which reads a local image by asking
the daemon for it — i.e. it runs `docker save` and reads blobs out of the resulting tar. On
servy, Docker runs on the **system containerd** (`dockerd --containerd=/run/containerd/
containerd.sock`, 27G under `/var/lib/containerd`) with the **containerd image store**.

For those 14 images the layer blobs are **gone from containerd's content store** while the
image record and the unpacked snapshots remain. `docker save` therefore emits a valid tar
whose `manifest.json` lists blobs it does not contain, and trivy aborts:

```
FATAL image scan error: failed to analyze layer (sha256:291bcf98…):
  failed to get the layer …: unable to open: failed to initialize the struct from the
  temporary file: file blobs/sha256/1fd2908c092e… not found in tar
```

Evidence:

| Check | Result |
|---|---|
| `docker save traefik:3.6.1` | **874 KB**, 7 blobs, **0 layer blobs** |
| `docker save nginx:stable` (scans fine) | 66 MB, 15 blobs, all 8 layers |
| `docker save leaguesphere/backend:latest` | **9.7 KB** |
| `ctr -n moby content get` on traefik's 4 layer digests | not found |
| traefik's manifest blob in the content store | still carries `gc.ref.content.l.0…3=` → **dangling refs** |
| `trivy image --image-src remote traefik:3.6.1` | works — the registry has the data |
| `docker export <ctr>` → `trivy rootfs` | works (178 MB rootfs) |
| `dockerd` log | `failed to calculate unpacked size of image … NotFound: content digest … not found` |

### Why the report called it "clean"

`run_trivy` ran `trivy image … 2>/dev/null` and, on any failure, appended `{}` to
`trivy-results.json`. Every consumer — the `grep -c '"Severity": "CRITICAL"'` counter, the
SUMMARY, later parsing — reads `{}` as zero findings. Nothing anywhere said "not scanned".

### Why the blobs disappeared (not capacity)

Storage was never the constraint: the root filesystem sits at 51G/75G (71%, 21G free) after
the 2026-10-27 reclaim deliberately took it from 90% to 63%. Deletion here is
**reference-driven, not space-driven**: `docker-cleanup.timer` runs
`docker system prune -a -f --volumes` **daily** since 2026-10-27, while Watchtower re-pulls
every app image (`~1.3G/day` of superseded layers) in the same shared containerd store.
Content blobs get collected, unpacked snapshots survive — containers keep running, and only
export/`docker save` breaks. The exact actor (prune vs. BuildKit GC) is not proven; the
signature is image records plus dangling content refs.

Note this was invisible until now: every earlier trivy result file is unparsable
(`2026-09-10`…`10-04` fail at char 40 — the old empty-`result` bug; `2026-08-30`…`09-09` at
~2 MB — the trivy-log-format bug). `2026-10-09` is the first readable report.

## Decision

Do not depend on the local image store for scanning, and never write a fake-clean row.

- **Fallback:** when `trivy image` fails, scan the container's merged filesystem
  (`docker export` → unpack → `trivy rootfs`). That reads through the runtime's snapshot, not
  the content store, so it is independent of the storage driver and image-store backend and
  is the only path that also covers images built on the host with no registry.

  Two traps found by running it for real instead of trusting the stub:
  - `trivy rootfs -` does not read stdin (`lstat -: no such file or directory`)
  - `trivy rootfs <tar>` **exits 0 with an empty result set** — the very fake-clean this
    change removes. On a real export: tar → 0 results, unpacked directory → 930. The export
    is therefore streamed through `tar -x` into a temp dir (deleted per image), and the test
    stub rejects a non-directory argument so the contract cannot silently regress.
- **Honest rows:** a row now carries either `result` + `scanner` (`image`/`rootfs`) or
  `error`. trivy's stderr is no longer discarded, so the FATAL line reaches `trivy.log`.
- **Coverage in the report:** `trivy-summary.txt` publishes `scanned`/`failed`/`critical`/
  `high`/`failed_target`, and `SUMMARY.md` shows `Container images: N/M scanned` plus a
  `## Scan Failures` list.
- Counts travel through files because `run_tool` runs each tool as `"$@" 2>&1 | tee …`, a
  subshell, so variables never propagate back.

Rejected: more storage (does not stop reference-driven deletion), `--image-src containerd`
(same content store, and `--containerd-addr` does not exist in trivy 0.74), re-pulling
(breaks again at the next prune), `--image-src remote` as the primary path (registry-only,
useless for host-built images).

## Implementation

- `ansible/plays/roles/system/templates/security-audit.sh.j2` — `json_ok()`, `scan_image()`,
  `scan_rootfs()` (+ fallback wiring, error rows, stats file, coverage in SUMMARY)
- `ansible/plays/roles/system/tests/test_security_audit_trivy.sh` — new harness: renders the
  template with jinja2, stubs `docker`/`trivy`, and asserts on the produced JSON, stats and
  SUMMARY (23 checks; run on a host with bash, e.g. servy)
- `docs/plans/2026-10-28-trivy-store-agnostic-scan.md`

Two reporting bugs fixed on the way: `Trivy: N CRITICAL, 0\n0 HIGH` (`grep -c` exits 1 on
zero matches, and `|| echo 0` appended a second 0) and `Tools Run` always reading `0` for the
same subshell reason.

## Verification

Deployed (`--tags system.security_audit.scripts`), then the audit re-run on 2026-10-28.
The deployed script is byte-identical to the rendered template at `f687a35`.

`/var/log/security-audit/2026-10-28/trivy-results.json`:

- **46 rows, 46 with `result`, 0 with `error`** (the fleet is 46 images today, not 47 —
  `job-search` was retired on 2026-10-27, `alpine/socat` and the moodle image were added)
- `scanner=image` for 34, `scanner=rootfs` for 12 — the fallback carried exactly the images
  whose blobs are gone: `bumblecode/ibs`, `emarcs/nginx-git`, `cadvisor`, `promtail`, all six
  `leaguesphere/*`, `ofelia`, `pushgateway`
- `traefik:3.6.1` scanned through the image path again — Watchtower re-pulled it since the
  broken run, which restores content blobs. That is the predicted behaviour, and it means
  the rootfs rows will move in and out as images are re-pulled
- `trivy-summary.txt`: `scanned=46 failed=0 critical=108 high=2663`

The rootfs rows are real now (this is what the unpack fix bought): `leaguesphere/backend`
199 vulns (3 sections: debian + node-pkg + python-pkg), `bumblecode/ibs` 186, `cadvisor` 84,
`promtail` 54, `pushgateway` 56 — before the unpack fix the same 12 images returned 0.

Do **not** compare `108 CRITICAL / 2663 HIGH` with 2026-10-09's `61 / 1246`: that report
covered 33 of 47 images, this one covers all 46, and the DB moved on by 19 days.

## Consequences

### Positive

- An unscannable image is now a visible failure, not a silent pass
- Scanning no longer depends on whether `docker save` can export the image
- The monthly report states its own coverage

### Negative / Tradeoffs

- The fallback costs a `docker export` per affected image (hundreds of MB each, deleted
  immediately after the scan) and scans the *container* filesystem, which includes runtime
  writes — acceptable for CVE purposes, but it is not a byte-identical image scan
- The root cause of the blob deletion is still unproven; expect `scanner=rootfs` to remain
  common until the prune/store interaction is understood

### Known Issues / Open Findings

- Why blobs referenced by live images are deleted from the content store is not established
  (daily `docker system prune -a` + Watchtower churn suspected). `docker save` on this host
  is unreliable for anything else too.
- `traefik:3.6.1` is 11 months old and the `fireflyiii/*` pair carry 23 CRITICAL each — the
  base images deserve their own look now that the numbers are trustworthy.
