# ADR: Cut the opencode container's boot cost, and make graphify work on aarch64

**Date:** 2026-11-17
**Status:** Accepted — Part 1 shipped to both hosts; Part 2 (derived image) planned
**Relates to:** ADR `2026-11-17_oracle-codey-replication` (the move that exposed it)

## Context

Every container recreate of the opencode dev gateway left it unable to answer for
roughly two minutes. Measured on the Oracle replica from container start to the
`listening on` log line:

| Phase | Cost |
|---|---|
| `apk` packages, chromium, YouTube Python deps | ~17 s |
| `graphify` pip install | **~44 s** |
| `provision-dev` (16 repo fetches) | **~43 s** |

Two of those were pure waste:

- **graphify** was installed on every boot into the image rootfs, which is
  discarded on recreate. Worse, on aarch64 it could never succeed: its
  dependency set was assumed to be `musllinux_1_2_x86_64`-only, so pip ignored
  the wheels, tried to compile ~20 tree-sitter language packs from source and
  failed after 44 s — every boot, for nothing.
- **provision-dev** is idempotent but does ~43 s of git round-trips across 16
  repos, on the critical path, before the server may start.

## Decision

**Part 1 — reorder the boot so optional work leaves the critical path.**

- `graphify`: skip outright on non-x86_64 (it cannot work there); where it can
  run, install in the background. Safe because opencode is a **Node** app — the
  Python packages underneath are only used later by the graphify CLI and
  `yt_upload.py`, so upgrading them cannot affect the running server.
- `provision-dev`: blocking only on a host that has never provisioned, in the
  background afterwards, gated on a `/root/dev/.provisioned` sentinel. The
  sentinel lives on the volumes volume (survives recreates) and is written only
  on success, so a failed first provision retries instead of locking in an empty
  `/root/dev`.

**graphify on aarch64 — it is achievable, the assumption was wrong.**

Only the **core `tree-sitter`** package lacks a musllinux-aarch64 wheel at every
version (x86_64 has one). 16 of 26 language packs do publish one — but only on
older versions, and pip prefers the newest sdist over an older wheel, so it
tried to compile them and died on:

```
tsx/src/parser.c:1:10: fatal error: tree_sitter/parser.h: No such file
```

(tree-sitter ≥ 0.25 no longer ships those C headers.) The recipe, implemented in
`opencode/scripts/install-graphify.sh`:

1. compile the core package (Rust toolchain — it is a maturin/pyo3 extension);
2. install language packs with `--only-binary=:all:` so pip backtracks to
   versions that actually have an aarch64 wheel;
3. install `graphifyy` itself with `--no-deps`, since its tighter pins would
   drag the sdists back in.

Result lands in `/root/.graphify-pkgs` — a `PYTHONPATH` entry on the persistent
volume — so it costs one build per host, not one per boot.

## Consequences

### Positive

- ✅ Steady-state boot **105 s → 22 s** (codey, x86_64) and **26 s** (Oracle,
  aarch64) — measured with real container recreates, not `docker restart`.
- ✅ graphify works on aarch64, verified functionally (parsing real source, not
  just `import graphify` — which succeeds even when `tree-sitter` is absent and
  gave a false pass during development).
- ✅ x86_64 also installs into the volume now, so codey no longer re-runs ~40 s
  of pip on every recreate.
- ✅ First boot stays blocking, so a fresh host never serves a session against
  an empty `/root/dev`.

### Negative / Tradeoffs

- ⚠️ On x86_64 graphify is briefly unavailable after a recreate (until the
  background install finishes); this only applies to containers created before
  the volume install existed.
- ⚠️ Only **16 of 26** language packs have an aarch64 musl wheel. `kotlin, objc,
  swift, lua, powershell, elixir, fortran, verilog, zig, groovy` are skipped —
  graphify imports and parses the rest, but those languages are not covered on
  the A1.
- ⚠️ A session started in the first seconds of a background `provision-dev` can
  see a repo mid-fetch.
- ⚠️ The residual ~22–26 s is almost entirely section 1 of `startup.sh` (apk +
  chromium + YouTube deps), which this ADR deliberately does not fix.

### Implementation Details

**Files:**
- `opencode/scripts/startup.sh` (MODIFY) — graphify arch-gating + backgrounding,
  provision-dev sentinel.
- `opencode/scripts/install-graphify.sh` (NEW) — the aarch64 build recipe.
- `opencode/docker-compose.yml` (MODIFY) — `PYTHONPATH=/root/.graphify-pkgs`.
- `docs/plans/2026-11-17-opencode-derived-image.md` (NEW) — Part 2 plan.

**Commits:** `d6acffb` (Part 1), `0cb32cd` (aarch64 graphify), `b7ec9f3`
(x86_64 uses the volume too), `a23562d` (Part 2 plan).

**Testing & Verification:**
- Boot measured twice per host: cycle 1 (sentinel absent, blocking) and cycle 2
  (steady state). Oracle 62 s → 26 s; codey 80 s → 22 s.
- Both hosts: `tree-sitter OK: module` when parsing `x = 1`.
- `/root/.graphify-pkgs` = 143.5 MB, confirmed inside the persistent volume.

### Known Issues & Limitations

- `codey_dev_checkouts` is excluded from restic, so uncommitted work in
  `/root/dev` is not backed up (see the replica ADR).
- The missing aarch64 language packs are a coverage gap, not a bug to fix: no
  wheel exists for those versions.

## Alternatives Considered

**Skip graphify on aarch64 permanently** — the original plan. Rejected: the user
needs the skill on the instance that now runs the codey role, and the assumption
it was impossible turned out to be wrong.

**Provide the C headers and compile the pinned versions** — would have kept
graphifyy's exact pins. Rejected: more fragile, and compiling 10+ C grammars for
packs that already ship a usable wheel is pure cost.

**Part 2 (derived multi-arch image) as the immediate fix** — bakes everything, so
boot drops under 10 s and graphify needs no runtime build. Deferred to its own
plan because it needs a CI publish path; Part 1 captures most of the win now
with a ~10-line change.
