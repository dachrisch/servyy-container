# runny is a global runner again

**Date:** 2026-11-24
**Status:** ✅ Live on servy.lehel.xyz / ci.lehel.xyz
**Relates to:** `2026-11-23_runner-rootless.md` (which introduced the scope),
`ci/AGENTS.md` "Registration model"

## Problem

Task 6 of the rootless-runner plan registered runny with `--scope cda`. That
was a reasonable stopgap while the runner was being proven, but it means
`bumbleflies/*` repos cannot use the native amd64 runner. The dontforget
Forgejo probe (2026-11-24) showed why that matters: a QEMU-built amd64 image
cannot be *run* on codey (it goes `unhealthy` immediately), so image
healthchecks need native amd64.

## Change

- `ansible/production`: `forgejo_runner_scopes: {}` (was `{runny: cda}`).
- `forgejo_bootstrap` defaults and `ci/AGENTS.md`: document both runners as
  global.
- Re-register runny via `./servyy.sh --limit servy.lehel.xyz --tags
  user.docker.ci.bootstrap` so the server-side registration drops the scope.
  `--keep-labels` preserves the single `amd64` label.

The scope was a defence-in-depth measure, not the security boundary: runny has
no repo checkout, no secrets and a rootless Docker daemon, so a job on any
repo cannot reach servy's git-crypt checkout or codey's credentials.

## Verification

`GET /admin/actions/runners` shows runny with `owner_id = 0` and only the
`amd64` label; codey is unchanged (`ubuntu-latest`, `docker`, `arm64`). No
runner restart needed — registration is re-read from the shared secret.

## Decisions recorded same day

- Knope is the chosen release-please replacement, with **default `vX.Y.Z`
  tags** fleet-wide. The spike (release event vs tag push, PAT-triggered
  downstream workflow) is still pending; see
  `setup-home/agent-config/skills/migrating-repos-to-forgejo/references/ci-port.md`.
- The `bumbleflies/queen` pilot is deferred.
