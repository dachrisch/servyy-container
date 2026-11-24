# Knope patch-release cycle proved on Forgejo

**Date:** 2026-11-24
**Status:** ✅ End-to-end on `cda/dontforget` (probe repo)
**Relates to:** `history/2026-11-24_renovate-self-hosted.md`,
`ci/docker-compose.yml` (router rate limit)

## What ran

1. `knope.toml` + two workflows added to the Forgejo probe's `master`:
   `prepare-release` (push to master → release PR) and `release` (release PR
   merged → Knope release + amd64 image job with `needs: [release]`).
   Knope 0.24.0 is installed from a pinned, checksum-verified tarball.
2. `fix: exercise Knope patch release cycle` pushed to master → release PR
   **#367** `chore: prepare release 0.28.81` (branch `release`), bumping
   `package.json` and adding a changelog entry.
3. PR #367 merged via the Forgejo API → Knope created tag **v0.28.81** and a
   Forgejo release; the image job built/pushed
   `ci.lehel.xyz/cda/dontforget:0.28.81` and `:latest`.
4. No release-PR loop: the prepare workflow skips `chore: prepare release`
   commits; only the two pre-existing feature PRs remain open.

## Fix required

The first image push failed with **429 Too Many Requests** from buildx blob
HEADs. The CI router carried Traefik's `crawler-ratelimit@file` (User-Agent
keyed, 10/s burst 20). The websecure entrypoint already applies the per-IP
`edge-guard` (25/s burst 600), so the router label was removed in
`ci/docker-compose.yml` and deployed with `--tags user.docker.repo,user.docker.ci`.
After rerunning the workflow both jobs were green.

Forgejo Actions secret names are alphanumeric only: `GITEATOKEN` and
`FORGEJOPACKAGETOKEN` were seeded via `fj` from the dedicated Forgejo PAT and
the managed API token.

## Decisions confirmed

- Knope is the release-please replacement; default `vX.Y.Z` tags fleet-wide.
- Trigger the image build from the release workflow (`needs: [release]`), not
  from `push.tags` — an API-created release's tag event is not reliable here.
- The pattern and gotchas are recorded in
  `setup-home/agent-config/skills/migrating-repos-to-forgejo/references/ci-port.md`.
