# `opencode:latest` is the V1 line — a compose recreate downgraded the server and hid every session

**Date:** 2026-11-05
**Status:** ✅ Rolled back to `2.1.2`, pinned, sessions verified intact (75 sessions / 10 413 messages)
**Relates to:** `2026-11-05_sshole-musl-sshd-audit.md`, `docs/plans/2026-10-25-prod-db-temp-credentials.md`

## Context

While deploying the sshd removal (previous entry), an `ansible --tags user.docker.opencode`
run executed the `docker_service` role and recreated `opencode.web` from the compose file.
The container had been running for six days on **v2.1.2**, while the compose file floated on
`image: ghcr.io/anomalyco/opencode:latest`. Watchtower only re-pulls the tag a container
already has, so the drift had never mattered — until a recreate read the file.

`ghcr.io/anomalyco/opencode:latest` is **not** a v2 build:

```
docker run --rm --entrypoint sh ghcr.io/anomalyco/opencode:latest -c 'opencode --version'
  1.19.5                       # V1 line
docker run --rm --entrypoint sh ghcr.io/anomalyco/opencode:2.1.2 -c 'opencode --version'
  opencode v2.1.2              # V2 line
```

The server was silently downgraded from V2 to V1. V1 does not read the V2 database
(`/root/.local/share/opencode/opencode.db`); it reads the legacy
`~/.local/share/opencode/storage/` tree, which on this host only holds a `migration`
marker from Sep 17. From the operator's side every session and all history had vanished.

The `/health` anomaly from the previous entry is the same fact: V1 answers `401` there,
V2 answers `200`. The old healthcheck comment had already recorded "V1 answered 401" —
it was describing exactly the image `latest` now points at.

## Decision

Restore service first, then remove the trap:

1. Roll the container back to **`ghcr.io/anomalyco/opencode:2.1.2`** (already on disk, and
   the version that was proven against this database).
2. Pin the image in `opencode/docker-compose.yml` with a comment explaining that `latest`
   is the V1 line, plus the pre-bump check
   (`docker run --rm --entrypoint sh <tag> -c 'opencode --version'` must print `opencode v2.x.y`).

Nothing was migrated, deleted or repaired by hand: the volume was never touched, only the
server process changed lines.

## Consequences

### Positive

- ✅ Every session, message and project is back — the UI reads the same 115 MB
  `opencode.db` it always did.
- ✅ The downgrade trap is gone: a recreate can no longer change product line, only the
  pinned v2.1.2 tag.
- ✅ The `/health` tolerance added in the previous entry stays correct for both
  generations (200 on 2.1.2, 401 on the V1 build).

### Negative / Tradeoffs

- ⚠️ Pinned to 2.1.2, so upstream fixes in later v2 tags no longer arrive automatically.
  `2.2.2` exists on ghcr (verified `HTTP 200` on its manifest) and is the obvious next
  step, but it must be tested against a **copy** of the volume first.
- ⚠️ Anything done inside the V1 window (≈23:05–23:24 on 2026-11-05) landed in the V1
  `storage/` tree and does not appear in V2.

### Implementation Details

**Files modified**

- `opencode/docker-compose.yml` — `image:` pinned to `2.1.2`; comment records that
  `latest` = V1 and how to verify a tag before bumping.

**Commits**

- `594d16c` fix(opencode): pin the V2 image, `latest` is the V1 line

**Testing & Verification**

- Version check on both images (`1.19.5` vs `opencode v2.1.2`) — the single fact that
  explains the symptom.
- Database read-only count **before** the rollback: 25 tables, `session_v2` 75,
  `session_message` 10413, `project` 33, `event_sequence` 95 → nothing lost.
- After rollback: `docker ps` → `Up (healthy)`, `/health` → `200`, `/session` → `200`
  (the V1 build answered `401` on both), `opencode.db` mtime advancing again, and the
  same counts read back through the running container.
- `/usr/sbin/sshd` still absent on the rolled-back container, `apk world` still
  `openssh-client-default` only.

**Key Learnings**

1. **`latest` is not "newest"** — for this image it is a whole other product line. Read
   `opencode --version` from the tag, never assume from the registry name.
2. **Watchtower tag semantics hide drift**: a container created from `2.1.2` keeps
   re-pulling `2.1.2` forever, so a compose file that floats on `latest` looks harmless
   until someone runs compose by hand or in Ansible.
3. **The data was never at risk**: sessions live in the volume, and the failure was
   purely which binary opened it. Check the DB (and count rows) before attempting any
   restore or migration.
4. **A "healthcheck flip" is a version signal.** An unexplained 200→401 on `/health`
   was the first symptom of the downgrade and had already been documented as V1
   behaviour months earlier.

### Known Issues & Limitations

- `servyy-test.lxd` runs its own `opencode.web`; if it is recreated from the old compose
  revision it will hit the same downgrade. It needs the pinned file on its next deploy.
- The V1 window's data (`storage/`) is not merged into V2; the ~20 minutes of activity
  there is effectively orphaned.
