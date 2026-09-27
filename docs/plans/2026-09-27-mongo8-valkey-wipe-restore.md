# Mongo 8 + Valkey Wipe-and-Restore Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move leagues-finance and job-search to mongo:8 + valkey:9-alpine by wiping volumes and restoring data, bypassing live migration.

**Architecture:** Since all data is restorable, skip FCV/mongodump migration complexity. Pin images to prod-proven digests, fix the FCV-gate bug, verify fresh start on servyy-test with empty volumes, then wipe-and-recreate on prod with restore.

**Tech Stack:** Ansible (ansible/plays/user.yml), Docker Compose (job-search, leagues-finance), mongo:8, valkey:9-alpine

---

### Task 1: Fix FCV-gate bug + pin prod-proven images

**Files:**
- Modify: `ansible/plays/user.yml:746-762`
- Modify: `job-search/docker-compose.yml:5`
- Modify: `leagues-finance/docker-compose.yml:21`
- Modify: `job-search/docker-compose.yml:22`
- Modify: `leagues-finance/docker-compose.yml:40`

**Step 1: Fix FCV set to run only on mongo:8**

Current bug: `Set leagues-finance mongo FCV to 8.0` runs whenever post-FCV==7.0, even on mongo:7 → `Invalid featureCompatibilityVersion '8.0'`.

Change `ansible/plays/user.yml` post tasks to add image gate:
```yaml
when:
  - "'leagues-finance' in (services | default([]))"
  - lf_mongo_post_fcv.stdout | default('') | trim == '7.0'
  - not (lf_mongo_upgrading | default(false)) or true  # replace with image check
```
Minimal correct fix: only set FCV 8.0 when container image is mongo:8. Add a `lf_mongo_is_v8` fact from `lf_mongo_upgraded_info.container.Config.Image is match('mongo:8')` and gate both lf + js set-FCV tasks on it. Same for `job-search` task at `~814-816`.

**Step 2: Pin to prod-proven digests**

Prod working set today (verified read-only):
- `mongo:8 e0ce8c35124d` (dontforget.mongo Up 2 weeks healthy)
- `valkey/valkey:9-alpine ee91f7a174ac` (searxng.valkey Up 2 weeks)
- Prod kernel `7.0.0-31-generic`, test `7.0.0-30-generic`

Test pulled floating `mongo:8` and hit `SERVER-121912` fresh-start failure. Pin both compose files to the prod digest until the kernel story is resolved, e.g.:
```yaml
image: mongo:8@sha256:<digest-of-e0ce8c35124d>
image: docker.io/valkey/valkey:9-alpine@sha256:<digest-of-ee91f7a174ac>
```
Get digests via: `ssh servy.lehel.xyz "docker inspect mongo:8 --format '{{.RepoDigests}}'"` and same for valkey.

**Step 3: Syntax check**

Run: `cd ansible && ansible-playbook servyy.yml -i production --syntax-check`
Expected: `playbook: servyy.yml` with no errors.

**Step 4: Commit**

```bash
git add ansible/plays/user.yml job-search/docker-compose.yml leagues-finance/docker-compose.yml
git commit -m "fix: gate FCV-8.0 on mongo:8 and pin prod-proven digests"
```

### Task 2: Validate fresh start on servyy-test with empty volumes

**Files:**
- Test: `ansible/testing` (override services_enabled)

**Step 1: Ensure clean test host**

Run: `ssh servyy-test.lxd "docker ps --format '{{.Names}}'; docker volume ls | grep -Ei 'job-search|leagues-finance' || echo clean"`
Expected: only `opencode.web`, `claude-hub.hub`, no lf/js volumes (previous run cleaned).

**Step 2: Deploy wipe-and-restore flow on test**

Run: `cd ansible && ./servyy-test.sh --tags "user.docker.leagues-finance,user.docker.job-search" -e '{"services_enabled": {"devhub": true, "opencode": true, "leaguesphere": true, "claude-hub": true, "leagues-finance": true, "job-search": true}}'`
Expected: `leagues-finance.mongo` + `job-search-mongodb` reach `healthy` on pinned `mongo:8` with empty volumes; `leagues-finance.redis` + `job-search-redis-app` reach `healthy` on pinned valkey with empty volumes (no RDB v12 error because volumes are fresh).

**Step 3: Verify FCV + versions**

Run: `ssh servyy-test.lxd "docker exec leagues-finance.mongo mongosh --quiet --eval 'db.version()' 2>&1 | tail -n2; docker exec leagues-finance.redis valkey-cli ping"`
Expected: mongo version `8.x`, `PONG`. FCV read returns `8.0`, set-FCV task shows `skipping` or `ok` (not failure).

**Step 4: Restore smoke test**

Restore the restorable dataset per service runbook (user confirms source), then verify app health: `docker ps` shows `finance-api`, `job-search-api` healthy, HTTPS routing via test Traefik entrypoint `web` without TLS.

**Step 5: Cleanup test**

Run test `compose down -v` for both services + prune test images. Verify host back to 2 containers.

### Task 3: Prod pre-checks (read-only, no changes)

**Step 1: Confirm prod state**

Run: `ssh servy.lehel.xyz "uptime; df -h / | tail -n1; uname -r; docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep -E 'leagues-finance|job-search|dontforget|searxng'"`
Expected: disk ~86% (11G avail — flag if >90%), kernel noted, `leagues-finance.mongo mongo:7 Up`, `job-search` zero containers, `dontforget.mongo mongo:8 Up`, volumes `job-search_mongodb_data`, `job-search_redis_data`, `leagues-finance_mongo_data` present.

**Step 2: Confirm restore source**

Verify the restorable dump/snapshot exists and is recent (restic snapshot or app-level export). Record path + timestamp in the deploy log. Do not proceed if restore source is missing.

### Task 4: Prod wipe-and-recreate job-search (no live containers)

**Step 1: Down + wipe volumes (destructive, approved: data restorable)**

Run via Ansible (never manual SSH edits for config; volume wipe is the approved destructive step):
```bash
ssh servy.lehel.xyz "docker volume ls | grep job-search"
ssh servy.lehel.xyz "cd /opt/docker/job-search && docker compose down -v"
ssh servy.lehel.xyz "docker volume ls | grep job-search || echo wiped"
```
Expected: both `job-search_mongodb_data` + `job-search_redis_data` gone.

**Step 2: Deploy pinned compose**

Run: `cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "user.docker.job-search"`
Expected: `job-search-mongodb` + `job-search-redis-app` become `healthy` on `mongo:8`/`valkey:9` with fresh volumes.

**Step 3: Restore + verify**

Restore dataset, then: `docker logs job-search-api --tail 20`, `curl` service URL, Traefik router shows no 502/503.

### Task 5: Prod wipe-and-recreate leagues-finance (downtime window)

**Step 1: Safety dump (cheap, even though restorable)**

Run the existing pre-task path once while still on mongo:7, or a one-shot `mongodump --gzip --archive` copied to `leagues-finance/.backup/`. Record path.

**Step 2: Down + wipe mongo_data (destructive, approved)**

`leagues-finance.redis` has no volume (safe). Only `leagues-finance_mongo_data` is wiped:
```bash
ssh servy.lehel.xyz "cd /opt/docker/leagues-finance && docker compose down -v"
```
Note: current `user.yml:673` auto-wipe block is guarded by `not upgrading` — with fresh pinned images and no old container, this path is intentional here, not accidental.

**Step 3: Deploy + restore**

Run: `cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "user.docker.leagues-finance"`
Expected: `leagues-finance.mongo` healthy on `mongo:8`, FCV `8.0`, `finance-api` healthy. Restore, verify finance endpoints + Traefik.

### Task 6: Post verify + prune legacy images

**Step 1: Health sweep**

Run: `.claude/skills/check-server-status/check-status.sh servy.lehel.xyz`
Expected: `UP`, zero `NOT Up`, `leagues-finance.*` + `job-search-*` healthy on new images, fail2ban 3 jails, monit OK.

**Step 2: Prune only when unused (opt-in)**

Run: `cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "user.docker" -e prune_legacy_datastore_images=true`
Expected: removes `redis:7-alpine`, `mongo:7`, `mongo:7.0` (~1.3–2.4GB). Docker refuses in-use removal, so safe to run after both services healthy. Verify with `docker images | grep -Ei 'mongo|redis|valkey'`.
