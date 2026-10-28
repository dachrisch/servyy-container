# Lynis aborted every audit since the P6 hardening deploy

**Date:** 2026-10-28
**Status:** ✅ Fixed and redeployed to `servy.lehel.xyz`
**Relates to:** `2026-10-08_security-audit-trivy-empty-results.md`, `docs/plans/2026-10-08-host-hardening-p6.md`

## Context

While validating the trivy fix on the 2026-10-28 audit, the Lynis phase "passed" with

```
0 warnings   0 suggestions   (no hardening_index)
```

A host that had scored 61/100 with 1 warning and 43 suggestions on 2026-10-09 does not become
perfect. `lynis-report.dat` was **352 bytes** and `lynis.log` held the reason:

```
[WARNING]: Your profile '/etc/lynis/custom.prf' contains unexpected characters.
Fatal error: unexpected characters in profile. Stopping execution (security measure)
```

## Root cause

`ansible/plays/roles/system/templates/lynis-custom.prf.j2` wrote each rationale on the
`skip-test=` line:

```
skip-test=BOOT-5122                                  # GRUB password - Hetzner cloud, no OOB boot access
```

A Lynis profile allows no characters after a value. Lynis stops before running a single test
and still writes the report header plus `hardening_index`-less metadata, so the audit looked
like a clean host instead of a dead tool. Lynis also loads `/etc/lynis/custom.prf` from its
own profile chain, so even an explicit `--profile` of a correct file did not help.

Deployed 2026-10-09 23:39 — 21 hours *after* the last audit ran (01:54), so no post-hardening
measurement ever existed. The 61/100 from 2026-10-09 is still the newest real number, and it
predates the hardening itself.

Verified both directions on the host: the abort names `/etc/lynis/custom.prf`; with the same
rules stripped of trailing comments and the bad file out of the chain, `lynis audit system`
ran normally (no fatal, report accumulating tests). The profile was restored byte-identical
after that experiment.

## Decision

1. **Profile:** every rationale moved to its own `#` line above its `skip-test=`.
2. **Guard:** `run_lynis` now requires `hardening_index` in the report. Without it the tool is
   reported as failed (`WARN: lynis exited with non-zero status`) instead of silently
   succeeding, and `SUMMARY.md` prints `Lynis hardening index: unknown (lynis aborted, see
   lynis.log)` rather than omitting the number.
3. **Regression check:** the audit harness rejects any `skip-test=` line carrying a trailing
   `#`, so the profile format cannot regress quietly.

Rejected: keeping the rationale inline as trailing text without `#` (still "unexpected
characters"), and dropping the profile (the accepted-risk list is what keeps the score honest).

## Consequences

### Positive

- The hardening audit runs again; the index appears in `SUMMARY.md` next to the coverage line
- Two audit tools are now incapable of reporting "clean" when they did not run

### Negative / Tradeoffs

- `run_lynis` no longer swallows a failure, so a genuinely broken lynis turns the tool log red
  (that is the intent)

### Known Issues / Open Findings

- The `skip-test=KRNL-6000:<sysctl>` and `skip-test=SSH-7408:Port` entries were never proven to
  match Lynis' control names; with the profile finally parsed, expect some of those findings to
  reappear and confirm whether the skip syntax is right
