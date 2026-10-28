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

## Verification

Deployed via `--tags system.security_audit.scripts`; `/etc/lynis/custom.prf` is byte-identical
to the rendered template. A standalone `lynis audit system --quick --cronjob --profile
/etc/lynis/custom.prf` then ran on `servy.lehel.xyz`:

| | before (2026-10-09, pre-hardening) | broken (since 2026-10-09 23:39) | now |
|---|---|---|---|
| `hardening_index` | 61 | **absent** | **81** |
| warnings | 1 | 0 (fake) | 3 |
| suggestions | 43 | 0 (fake) | 14 |
| `lynis-report.dat` | 66 KB | **352 bytes** | 65 KB |
| fatal errors | — | `unexpected characters in profile` | 0 |

`+20` over the pre-hardening baseline is the P6 hardening finally being measured. Warnings
now are `PKGS-7392` (vulnerable packages), `MAIL-8818` (SMTP banner leaks OS/software name)
and `FINT-4316` (no AIDE database) — the last one is an artefact of the scoped AIDE config:
the DB lives at `/var/lib/aide/aide-hardening.db` (9.7 MB, 2026-10-10), not the distro
`/var/lib/aide/aide.db` that Lynis looks for. See
`2026-10-10_host-hardening-aide-scope.md`.

Suggestions dropping from 43 to 14 is what the accepted-risk profile is for — it is finally
being read.

### The `skip-test=<ID>:<qualifier>` entries do nothing

Lynis 3.1.6 does not honour the qualified form. `skip-test=SSH-7408:Port` did not suppress
`SSH-7408`; the control still evaluates and now reports a *different* sub-finding
(`AllowTcpForwarding (set LOCAL to NO)`). Suppressing the whole control instead would hide
genuine advice, so the entry stays inert on purpose. The three
`skip-test=KRNL-6000:<sysctl>` entries are equally inert, which is fine today only because
those sysctls are actually set by the hardening role. Do not add more qualified entries
expecting them to work.

## Consequences

### Positive

- The hardening audit runs again; the index appears in `SUMMARY.md` next to the coverage line
- Two audit tools are now incapable of reporting "clean" when they did not run

### Negative / Tradeoffs

- `run_lynis` no longer swallows a failure, so a genuinely broken lynis turns the tool log red
  (that is the intent)

### Known Issues / Open Findings

- `skip-test=<ID>:<qualifier>` is inert in Lynis 3.1.6 (see above); today's `KRNL-6000:*` and
  `SSH-7408:Port` entries are documentation, not suppression
- `FINT-4316` will keep firing while AIDE uses the scoped database path
- Two findings worth a look now that the audit is trustworthy again: `ACCT-9630` (auditd is
  running with an empty ruleset) and `MAIL-8818` (SMTP banner discloses OS/software)
