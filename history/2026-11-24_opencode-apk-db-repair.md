# opencode crash loop: broken apk DB, and the pending 2.4.1 bump

**Date:** 2026-11-24
**Status:** ✅ Accepted — deployed to `codey.lehel.xyz` and verified
**Relates to:** [opencode/scripts/AGENTS.md](../opencode/scripts/AGENTS.md),
[history/2026-11-13_opencode-container-bash.md](2026-11-13_opencode-container-bash.md)

## Context

`opencode.web` on codey was in a restart loop: `Restarting (1)`, `RestartCount=160`,
`ExitCode=1`, created 2026-11-19, image `ghcr.io/anomalyco/opencode:2.3.2`. Every boot stopped
at the same place in `opencode/scripts/startup.sh`:

```text
🔧 [Startup] Initializing development environment...
📦 [Startup] Installing system packages...
v3.24.4-184 ... [main]
v3.24.4-185 ... [community]
OK: 28591 distinct packages available
1 error; 930.6 MiB in 255 packages
```

`apk add` suppresses the detail on stdout, so the logs looked like an unexplained `1 error`.
Reproducing it against a `docker commit` of the live container and running `apk fix` revealed the
real cause:

```text
ERROR: python3-ndbm-3.14.10-r2: trying to overwrite
usr/lib/python3.14/lib-dynload/_dbm.cpython-314-aarch64-linux-musl.so
owned by python3-3.14.10-r1.
```

The long-lived rootfs (image 2.3.2, 255 packages, ~930 MiB) held an inconsistent apk DB from an
interrupted python3 `r1 → r2` transaction — Alpine 3.24 split `_dbm` out into `python3-ndbm`.
`apk add` then exits 1, and `startup.sh`'s `set -e` turns one package hiccup into a permanent
restart loop.

Evidence, before changing anything:

| Probe | Result |
|---|---|
| fresh container, same image, same `apk add` | exit **0** (rootfs state, not image/repo) |
| committed live container's rootfs, same `apk add` | `1 error`, exit 1 — reproduced |
| `apk fix --force-overwrite` on that rootfs, then `apk add` | both exit **0** — repair works |
| `apk fix --force-overwrite` on a healthy rootfs | ~0.7 s no-op — safe to run every boot |
| `docker inspect` image vs host compose image | `2.3.2` running, compose pinned `2.4.1` since 2026-11-23 (Renovate #341/#345); `2.4.1` not pulled locally |

## Decision

1. **Repair the apk DB before installing packages, and never let apk abort the boot.** Extracted the
   system-package section of `startup.sh` into `opencode/scripts/apk-bootstrap.sh`, which runs
   `apk fix --force-overwrite` first, retries a failed `apk add` once after a forced repair, and
   warns-and-continues if apk itself is broken. The remaining apk-dependent steps in `startup.sh`
   (`envsubst`, the `git config` block) are guarded too, so the image's `opencode serve` can still
   start. `envsubst` now writes to a temp file and only replaces `opencode.json` on success.
2. **Test the boot contract without a broken container.** `opencode/tests/test_apk_bootstrap.sh`
   stubs `apk` and asserts: broken DB is repaired before `add`, a healthy DB installs once, and an
   unrepairable apk never aborts the boot. Wired into CI as a path-gated `test-opencode-scripts`
   job added to `CI Gate`.
3. **Apply the pending 2.4.1 bump** (already in `opencode/docker-compose.yml`) after validating it
   against a copy of the live volume, per the rule in that compose file.

## Consequences

### Positive

- ✅ The known failure class self-heals on the next boot; one apk error can no longer crash-loop the service.
- ✅ The boot helper is contract-tested in CI, not just in a chat session.
- ✅ Running image matches the compose pin (`2.4.1`).

### Negative / Tradeoffs

- ⚠️ If apk is genuinely unusable, the container now starts with **degraded tooling** (no git/ssh/envsubst)
  instead of crash-looping. The warning is in `docker logs`; a healthy-DB boot is unaffected. This is
  deliberate: a loud log line plus a reachable API is preferable to a restart loop that hides the cause.
- ⚠️ `apk fix --force-overwrite` can overwrite files owned by another installed package. That is exactly
  what is needed to clear the split-package conflict, and it is scoped to this container's rootfs.

## Files changed

| Path | Change |
|---|---|
| `opencode/scripts/apk-bootstrap.sh` | NEW — apk DB repair + guarded package install, testable via `APK` override |
| `opencode/scripts/startup.sh` | §1 delegates to the helper; `envsubst` temp-file guard; `git config` block guarded |
| `opencode/tests/test_apk_bootstrap.sh` | NEW — 7 stub-based contract assertions |
| `ansible/plays/roles/opencode/tasks/main.yml` | deploy the new helper with a restart notification |
| `.github/workflows/ci.yml` | `opencode` path filter, `test-opencode-scripts` job, added to `CI Gate` needs |
| `opencode/docker-compose.yml` | unchanged — already pinned to `2.4.1`; this deploy applies it |

## Verification

```bash
# local
sh -n opencode/scripts/startup.sh opencode/scripts/apk-bootstrap.sh
sh opencode/tests/test_apk_bootstrap.sh                 # 7 passed, 0 failed
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
python3 .github/scripts/molecule_matrix.py --all
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing

# 2.4.1 image validation (against a COPY of the live volume, never prod itself)
docker pull ghcr.io/anomalyco/opencode:2.4.1
docker run --rm --entrypoint sh ghcr.io/anomalyco/opencode:2.4.1 -c 'opencode --version'
#   -> opencode v2.4.1
# copy opencode_opencode_root -> opencode-validate-241, boot 2.4.1 on :4097
#   -> health=200, /api/info=401
#   -> session_v2 49, session_message 8404, project 34  (identical before/after)
# validation container + volume removed afterwards

# deploy (test host first, then prod)
cd ansible && ./servyy-test.sh --limit servyy-test.lxd --tags user.docker.opencode
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
#   test: ok=193 changed=6 failed=0 -> opencode.web Up, healthy on 2.4.1
#   prod: ok=251 changed=18 failed=0 -> opencode.web Up (healthy), image 2.4.1,
#         RestartCount=0, boot log "apk database checked" -> "system packages ready"
#   note: the first test run was blocked by a stale /tmp/opencode-superpowers-upstream
#         controller clone (all files deleted, no local edits); removing that disposable
#         staging dir and re-running passed. No repo change needed.

# post-deploy
ssh codey.lehel.xyz "docker ps --filter name=opencode.web --format '{{.Names}} {{.Status}}'"
ssh codey.lehel.xyz "docker logs --tail 40 opencode.web"
.claude/skills/check-server-status/check-status.sh codey.lehel.xyz
```
