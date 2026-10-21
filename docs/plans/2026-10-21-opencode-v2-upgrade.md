# OpenCode V1 → V2 upgrade on codey (1.19.3 → 2.1.2)

> **For the executing agent:** follow the tasks in order. Each task lists the exact files, commands and expected output. Do not skip the servyy-test phase — this is a production agent host.

**Goal:** move `opencode.web` on `codey.lehel.xyz` from OpenCode V1 `1.19.3` (image `ghcr.io/anomalyco/opencode:latest`, which upstream still points at the V1 line) to V2 `2.1.2` (versioned image tag), with config, health monitoring, session pruning and the two local plugins working again.

**Architecture:** the container stays a foreground `opencode serve` process behind Traefik; the V2 server keeps the same Basic-auth contract (`OPENCODE_SERVER_PASSWORD`) and the same data directory, so the existing authgate, volume and DB are kept and the V1 SQLite DB is migrated in place on first boot. Code changes are confined to `opencode/` (compose, startup script, config template, prune script) and are deployed through the existing Ansible `user.docker.opencode` path.

**Tech stack:** Docker Compose, Alpine 3.24 musl image, Node/Bun plugin API (V2), SQLite, Ansible, Molecule-free service deploy, Traefik + Caddy authgate.

---

## Verified facts this plan is built on

| # | Fact | How it was verified |
|---|---|---|
| 1 | codey runs V1 `1.19.3` from `:latest`; upstream `latest` is the V1 line | `docker exec opencode.web opencode --version`; `ghcr.io/v2/anomalyco/opencode/manifests/latest` = the running image; npm `opencode-ai@latest` = 1.19.3 |
| 2 | V2 is `2.1.2`, published as npm `@opencode/cli` and as **versioned image tags only** (`2.0.0`…`2.1.2`, no `2.x` alias) | npm dist-tags; registry manifest HEAD 200 for each 2.x tag |
| 3 | The V2 image is Alpine 3.24 + musl binary at `/usr/local/bin/opencode`, entrypoint `opencode`, runs as root, no exposed ports, 104 MB | image config blob + layer history of `2.1.2` |
| 4 | V2 has **no `web` subcommand** — `opencode web …` parses `web` as a *directory*; the server is `opencode serve --hostname … --port …` | `opencode web --help` (generic usage) vs `opencode serve --help` on 2.1.2 |
| 5 | `OPENCODE_SERVER_PASSWORD` still gives Basic auth on `serve` (401 without, 200 with `-u opencode:<pw>`) | probe `serve` on port 4097 |
| 6 | V2 `/health` answers **200 without auth** (V1 answers 401) → the current healthcheck command fails under V2 | same probe: `/health` → 200, `/api/info` → 401/200 |
| 7 | V2 migrates a V1 SQLite DB **in place** and keeps the legacy tables: my laptop's DB has `session` (325, legacy) *and* `session_v2` (333), `legacy sessions missing from v2: 0` | `~/.local/share/opencode/opencode.db` introspection |
| 8 | A DB copy taken with `docker cp` while the server is running is **corrupt** (`SQLiteError: database disk image is malformed`); a `sqlite3 .backup` copy is valid | both attempted against codey's live DB |
| 9 | V2 schema: `part`, `message`, `session`, `session_input`, `session_context_epoch`, `todo`, `session_share` are legacy; live data is in `session_v2`, `session_message`, `session_inbox`, `session_pending` (`event`/`event_sequence` unchanged) | fresh V2 DB + laptop DB comparison |
| 10 | `tool-output/` (flat files) and `snapshot/<project>/<repo>/` (git repos) still exist in V2 with the same layout | `~/.local/share/opencode/` on 2.1.2 |
| 11 | Both deployed plugins are already **V2 plugins** (`ctx.session.hook`, `ctx.tool.transform`) but codey runs V1 → they are inert: the live server reports only built-in tool ids, no `session_*` tools | `/experimental/tool/ids` on codey returns `invalid, question, bash, read, glob, grep, edit, write, task, webfetch, todowrite, websearch, skill, apply_patch`; last `session_*` tool call in codey's DB: 2026-10-16 (the V2 port was deployed 2026-10-18) |
| 12 | `opencode-working-memory@1.6.9` is V1-only: `peerDependencies: {"@opencode-ai/plugin": ">=1.2.0 <2.0.0"}`, last publish 2026-06-09, no newer version | npm registry metadata |
| 13 | Config compat: V2 reads the V1 config shape as-is; only `plugin`→`plugins` and TUI config (`tui.json`→`cli.json`) need touching | `https://opencode.ai/v2/docs/migrate-v1/` |
| 14 | V2 defaults that differ from V1: **todos off** (needs `experimental.todo: true`) and **`external_directory` allowed** (V1 asked) | same doc |
| 15 | codey has **2 vCPU, 1.9 GB RAM (~310 MB free), disk 91 % full (2.7 GB left)**; `opencode.web` already holds ~650 MB RSS | `free -m`, `df -h /`, `nproc`, `docker stats` |
| 16 | There is **no global `AGENTS.md`** on codey today (`/root/.config/opencode/` holds only `opencode.json`, `tui.json`, `plugins/`, `skills/`) | `ls` inside the container |
| 17 | V2 has a native, zero-dependency instructions channel: global `~/.config/opencode/AGENTS.md` + an `instructions` array (files, globs, URLs) that hot-reloads while a session runs | `https://opencode.ai/v2/docs/instructions/` |

Consequences of the above that shape the plan: the upgrade is a *fix* for #11, the healthcheck in the compose file (#6) will mark the container unhealthy the moment it restarts on V2, and the nightly prune job (#9) keeps running and silently prunes the legacy `session` table while live sessions live in `session_v2` — so it must be ported in the same change. Resource limits (#15) rule out the memory plugins that ship a local vector stack.

---

## Phase 0 — Decisions (resolved 2026-10-21)

| Decision | Chosen | Why |
|---|---|---|
| Image reference | **pin `ghcr.io/anomalyco/opencode:2.1.2`**, never `:latest` again | `latest` is the V1 line (#1/#2); a pinned tag makes Renovate and rollback meaningful |
| Renovate behaviour | **leave the existing rule alone** (`automerge: minor/patch`) | owner decision; a V2→V3 bump is a major and still arrives as a PR |
| Memory plugin (`opencode-working-memory`) | **drop it, replace with the V2-native instructions channel** (see "Memory research") | V1-only (#12) and the only feature-parity V2 candidate does not fit codey's resources (#15) |
| Todos | **add** `"experimental": { "todo": true }` | V2 off by default (#14); codey sessions use `todowrite` (20 calls in the current DB) |
| `external_directory` permission | keep V2 default (allowed) | an `ask` rule on an unattended server stalls sessions; the container is already a sandbox |
| TUI config (`tui.json`) | stop deploying it; delete the file | V2 terminal config is `cli.json`; the container runs no TUI, so the file is dead weight |
| V1 config shapes (`provider`, `mcp`, models) | keep for this change, convert later | explicitly optional per the migration guide (#13); smaller blast radius |

### Memory research (replaces `opencode-working-memory`)

`opencode-working-memory@1.6.9` automatically captures durable project facts, injects them at compaction time and exposes `/memory` in the TUI — no tools, no extra LLM calls. Its V1 peer range (`@opencode-ai/plugin >=1.2.0 <2.0.0`) means it cannot load on V2, and the `/memory` menu is TUI-only, i.e. useless on a headless server.

Candidates checked against the registry on 2026-10-21:

| Package | V2 support | Storage / runtime | Verdict |
|---|---|---|---|
| `opencode-mem@2.33.0` | explicit (`"plugins": ["opencode-mem@latest"]`) | embedded Turso/libSQL + `@huggingface/transformers` + `onnxruntime-node`; **0.5–2 GB RAM** while the embedding model is loaded, **100 MB–2 GB model cache** per model, model download on first use | **Rejected for codey** — does not fit 1.9 GB RAM / 2.7 GB free disk with a 650 MB server already resident (#15) |
| `@mathew-cf/opencode-memory@2.4.0` | explicit (`./server` export for v2, `plugins` list) | git-tracked markdown store at `~/opencode-memory/`, tools (`memory_save`/`memory_search`), compaction hooks, bundled skill, ~90 MB embedding model via `@mathew-cf/rag-cli` | Feasible fallback if automatic memory is required; heavier than the native channel and still adds an embedding model |
| `@openviking/opencode-plugin` | yes | **requires a separate OpenViking server** | Rejected — new infrastructure |
| `@log0u7/opencode-memory@0.5.0` | unknown | no README, no deps declared, single maintainer | Rejected — no signal to trust |
| **V2 native instructions** (`AGENTS.md` + `instructions`) | built in | plain files, hot-reloaded, zero dependencies, zero RAM | **Chosen baseline** (#17) |

What the native channel does and does not do: it restores *durable, curated* guidance across sessions (project facts, conventions, decisions) and beats the old plugin on portability and inspectability, but it does **not** auto-capture facts from a conversation. The task below migrates the durable part; if automatic capture is later judged necessary, `@mathew-cf/opencode-memory` is the pre-vetted option — and it should be benchmarked on codey's RAM before adopting.


---

## The API bridge: what survives, what breaks

The public API door is not just the healthcheck. `code.lehel.xyz` is consumed by three
services, and the `opencode-authgate` Caddy container is the bridge that lets two of them in
without the human password:

| Consumer | Auth | Calls |
|---|---|---|
| `dontforget` | `X-Api-Key` → forwardAuth injects Basic | `POST /api/session`, `POST /api/session/{id}/prompt`, `GET /api/session/{id}/message` (`src/search/opencodeClient.ts`) |
| `job-search` | same | the above plus `GET /api/model` for model discovery (`packages/api/src/ai/opencode.ts`) |
| `devhub` | Basic directly | create/prompt/message, `GET /api/model`, SSE `GET /api/session/{id}/event`, best-effort `POST /api/session/{id}/abort` (`src/lib/opencode.ts`) |

**The bridge itself needs no change.** V2's `serve` still accepts the Basic credentials
`OPENCODE_SERVER_PASSWORD` provides (verified: 401 without / 200 with), the authgate only
translates `X-Api-Key` into that same header, and every path the Traefik router allows
(`POST /api/session`, `/api/session/ses_*/...`, `GET /api/model`) exists in V2's API.

**The contract behind it does.** Compared against the live V1 spec (`/doc` on the running
1.19.3, 162 paths) and the V2 OpenAPI (121 paths, only **40 in common**):

| Call | V1 1.19.3 | V2 2.1.2 | Effect |
|---|---|---|---|
| `POST /api/session/{id}/prompt` | body `{prompt: {...}}`, `prompt` required | body `{text: "..."}`, `text` required | **breaks all three consumers** (400). Both schemas are `additionalProperties: false`, so no request body works on both versions |
| `POST /api/session` | `{id?, agent?, model?, location?}` | same set plus `parentID`/`title`/`metadata` | compatible |
| `GET /api/session/{id}/message` | `{data: [SessionMessage], cursor}` | `{data: [Session.Message.Info], cursor}`; assistant keeps `type`/`finish`/`content[]`/`error` | shape-compatible; **ordering and default page size must be verified live** — the pollers read `data[0]` as "newest" |
| `GET /api/model` | `{location, data: [ModelV2Info]}` | `{location, data: [Model.Info]}` — superset including `id`, `providerID`, `cost`, `status`, `enabled` | compatible |
| `POST /api/session/{id}/interrupt` | present | present | fine (use this instead of `/abort`) |
| `POST /api/session/{id}/abort` | absent | absent | already a no-op today; `devhub` should switch to `/interrupt` |
| `GET /api/session/{id}/event` (SSE) | present | absent (V2 streams `GET /api/event`) | `devhub`'s live progress view degrades to poll-only; it already treats SSE as best-effort |

**Sequencing.** Because the prompt body is mutually exclusive, the cutover cannot be made
backward compatible by sending both keys. Two workable options:

1. **Version-detect in the clients (recommended, zero downtime).** `GET /api/plugin` exists only
   in V2 (V1 answers 404; `/api/health` is the inverse, V1-only). Have each client probe once,
   cache the result, and send `{text}` on V2 / `{prompt:{text}}` on V1. Ship the clients first —
   they keep working against 1.19.3 — then upgrade OpenCode with no ordering constraint.
2. **Lockstep + pause.** Stop the `dontforget` and `job-search` schedulers, upgrade, deploy the
   fixed clients, restart them. Simpler, but a 400 during the window can mark models unhealthy in
   `job-search`'s cooldown registry, so it needs the schedulers genuinely paused, not just lucky
   timing.

Either way the client change is one line per repo at the prompt call, plus `abort` → `interrupt`
in `devhub`, plus a live check that `GET /api/session/{id}/message` returns newest-first.

---

## Phase 1 — Repository changes

### Task 1: Pin the image and fix the healthcheck

**Files:**
- Modify: `opencode/docker-compose.yml:3` (image), `opencode/docker-compose.yml:63-66` (healthcheck)

**Step 1: change the image tag**

```yaml
    image: ghcr.io/anomalyco/opencode:2.1.2
```

**Step 2: replace the healthcheck**

```yaml
    healthcheck:
      # Two assertions: liveness, then the auth contract. V2 answers /health
      # 200 without auth (V1 answered 401), so the old `grep '401 Unauthorized'`
      # probe both conflated liveness with auth and hid curl's exit status
      # behind the pipeline. An unauthenticated /api/info must still be 401 —
      # that is what catches a boot with a missing or rotated
      # OPENCODE_SERVER_PASSWORD.
      test: ["CMD-SHELL", "curl -fsS -o /dev/null http://127.0.0.1:4096/health && curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4096/api/info | grep -qx 401"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
```

Timings stay as they are on purpose: the watchtower health gate is a fixed
`WATCHTOWER_HEALTH_CHECK_TIMEOUT: "2m"` (`portainer/docker-compose.yml:66`), and the
current worst case is already `20 + 3 × (30 + 10) = 140 s`. Raising `start_period`
would push it further past that gate, so first-boot time is measured on the test
host instead (Phase 2) and the timings are revisited only with data.

**Step 3: verify the file still parses**

```bash
cd /home/cda/dev/infrastructure/container/opencode && docker compose config --quiet
```

Expected: no output, exit 0. (Compose reads `.env`/`opencode.env`; if they are missing locally, run `docker compose -f docker-compose.yml config --no-interpolate --quiet` instead.)

**Step 4: commit**

```bash
git add opencode/docker-compose.yml
git commit -m "feat(opencode): pin V2 image and fix healthcheck for V2 /health"
```

### Task 2: Start the V2 server instead of the V1 `web` command

**Files:**
- Modify: `opencode/scripts/startup.sh` (last line)

**Step 1: change the exec line**

```sh
echo "🚀 [Startup] Setup complete. Launching application..."
# V2 has no `web` subcommand (it would be parsed as a directory); `serve` is
# the foreground V2 API + web server. Basic auth still comes from
# OPENCODE_SERVER_PASSWORD (verified against 2.1.2).
exec opencode serve --hostname 0.0.0.0 --port 4096
```

**Step 2: delete the dead TUI config deployment**

Remove this block from `opencode/scripts/startup.sh`:

```sh
if [ -f "/scripts/tui.json" ]; then
    echo "⚙️ [Startup] Deploying tui.json..."
    cp /scripts/tui.json "$CONFIG_DIR/tui.json"
fi
```

and delete the file `opencode/scripts/tui.json` plus the matching Ansible task (`ansible/plays/roles/opencode/tasks/main.yml`, task "Deploy OpenCode TUI config").

**Step 3: syntax check the script**

```bash
sh -n /home/cda/dev/infrastructure/container/opencode/scripts/startup.sh && echo OK
```

Expected: `OK`.

**Step 4: commit**

```bash
git add opencode/scripts/startup.sh opencode/scripts/tui.json ansible/plays/roles/opencode/tasks/main.yml
git commit -m "feat(opencode): run V2 serve command and drop V1 tui.json"
```

### Task 3: Move the config template to the V2 plugin shape

**Files:**
- Modify: `opencode/scripts/opencode.json.template`

**Step 1: replace the plugin entry and add the todo flag**

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "experimental": {
    "todo": true
  },
  "mcp": { ... unchanged ... },
  "provider": { ... unchanged ... }
}
```

Notes:
- The `plugin` key is removed entirely rather than renamed to an empty `plugins: []` — an empty array carries no information. `plugin` is deprecated in the V2 schema in favour of `plugins`; local plugin files under `/root/.config/opencode/plugins` are auto-discovered and need no config entry. The memory plugin is dropped (#12) and its durable-facts role moves to the global `AGENTS.md` in Task 3b.
- `provider`/`mcp` stay in V1 shape on purpose.

**Step 2: confirm the template still renders**

```bash
cd /home/cda/dev/infrastructure/container/opencode && \
  CIRCLECI_TOKEN=x CIRCLECI_BASE_URL=y DASHSCOPE_API_KEY=z OPENCODE_GO_API_KEY=w \
  envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY $OPENCODE_GO_API_KEY' \
  < scripts/opencode.json.template | python3 -m json.tool > /dev/null && echo VALID
```

Expected: `VALID`.

**Step 3: commit**

```bash
git add opencode/scripts/opencode.json.template
git commit -m "feat(opencode): V2 plugins shape, enable todos, drop V1-only memory plugin"
```

### Task 3b: Restore durable cross-session memory via a global `AGENTS.md`

Replaces the dropped V1-only memory plugin with the V2-native instructions channel (#17). Scope: curated, durable facts — not automatic capture (see "Memory research").

**Files:**
- Create: `opencode/scripts/AGENTS.md`
- Modify: `opencode/scripts/startup.sh` (copy it into the config dir)
- Modify: `ansible/plays/roles/opencode/tasks/main.yml` (deploy the file to the host, next to the other `scripts/` files)

**Step 1: write the file**

Keep it short and factual — host layout, what this instance is for, verification commands, and any conventions that must survive a compaction. Everything in it is loaded into every session on codey, so no secrets and no volatile state.

The landed file is `opencode/scripts/AGENTS.md` — do not duplicate it here. It must cover, and must not contradict:

- the host (`codey.lehel.xyz`, container `opencode.web`), the public URL + Basic auth, and the `/root/dev` checkouts with their own `AGENTS.md`;
- that infrastructure changes go through the repo and Ansible, never manual host edits;
- **in-container** verification via loopback (`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4096/health` → 200) — the container has no docker CLI or socket, so `docker ps` / `docker exec` / `docker logs` must never be suggested without the `ssh codey.lehel.xyz "…"` host prefix, including the Ofelia prune log (`ssh codey.lehel.xyz "docker logs portainer.ofelia"`);
- the session DB path and the nightly 04:00 prune;
- that the repo file is the source of truth: `startup.sh` re-copies it on every boot, so in-container edits are lost on restart.

**Step 2: copy it during startup**

In `opencode/scripts/startup.sh`, inside the existing "Configuration Substitution" block (after `mkdir -p "$CONFIG_DIR"`):

```sh
if [ -f "/scripts/AGENTS.md" ]; then
    echo "🧠 [Startup] Deploying global AGENTS.md..."
    cp /scripts/AGENTS.md "$CONFIG_DIR/AGENTS.md"
fi
```

**Step 3: deploy it with the other scripts**

Add an Ansible task next to "Deploy OpenCode config template" in `ansible/plays/roles/opencode/tasks/main.yml`:

```yaml
- name: Deploy OpenCode global AGENTS.md (cross-session memory)
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../../opencode/scripts/AGENTS.md"
    dest: "{{ ('/home/', create_user, 'servyy-container/opencode/scripts/AGENTS.md') | path_join }}"
    mode: '0644'
  notify: restart opencode container
  tags: [user.docker.opencode]
```

**Step 4: verify the file lands and is honoured**

```bash
sh -n opencode/scripts/startup.sh && echo OK
ssh codey.lehel.xyz "sudo docker exec opencode.web cat /root/.config/opencode/AGENTS.md | head -3"
```

Expected: `OK`, then the first lines of the file after the next restart. Functional check: start a session on codey and ask "which host are you on and where do checkouts live?" — the answer must come from this file.

**Step 5: commit**

```bash
git add opencode/scripts/AGENTS.md opencode/scripts/startup.sh ansible/plays/roles/opencode/tasks/main.yml
git commit -m "feat(opencode): add global AGENTS.md as the cross-session memory channel"
```

### Task 4: Port the session pruner to the V2 schema (test-first)

**Files:**
- Modify: `opencode/scripts/prune-sessions.py`
- Test: `opencode/scripts/test_prune_sessions.py` (new)
- Modify: `.github/workflows/ci.yml` (run the suite in the Python test job)

The V1 pruner deletes from `part`, `message`, `session_message`, `session_input`, `session_context_epoch`, `todo`, `session_share` and then `session`. Under V2 (#9) live rows are `session_v2` + `session_message` (+ `session_inbox`, `session_pending`, `instruction_entry`, `instruction_state`) with `event`/`event_sequence` keyed by `aggregate_id`; the V1 tables survive a migration but are dead weight. Left alone, the nightly job would keep "pruning" the legacy `session` table, delete nothing live, and log success while the DB grows.

**Implemented (as landed, `e4b2c7e` + `4eb20dc`):**

1. **Selection is by inactivity, not creation**: both `time_created < cutoff` **and** `time_updated < cutoff`, with the live test as the exact complement (`time_created >= ? OR time_updated >= ?`). This came out of review: creation-only selection would have deleted a session created 74 h ago but active 0.9 h ago under the default window, and one session on the production 168 h window. Deleting a session mid-turn can also break the server's next write (FK to `session_v2`).
2. **Legacy cleanup is defensive**: tables are existence-checked via `sqlite_master` (a fresh V2 DB has none of them, and `session_input`/`session_context_epoch` are absent from some migrated DBs — the old script would have crashed there). Legacy rows are deleted only for ids that are **not** live in `session_v2`, and child rows are cleaned for **all** deleted ids, including V2-only sessions.
3. **Failure is loud**: a DB without `session_v2` exits 1 instead of silently succeeding. Deletes run in one transaction with an explicit `rollback()` on error.
4. **Counts are distinct sessions** (a session present in both tables is logged once), the `pruned N sessions: …` log format is unchanged, and `vacuum` still runs only when rows were deleted.
5. **`tool-output/` and `snapshot/<project>/<repo>/` pruning is untouched** (#10).

**Tests (`opencode/scripts/test_prune_sessions.py`, 17 cases, stdlib `unittest`)** build throwaway SQLite DBs and assert real deletes, including the guards that mutation testing proved were previously unpinned: a legacy row whose `session_v2` twin is live survives; a partially migrated schema runs cleanly; a V2-only stale session is pruned (pins selection from the right table); a long-lived-but-active session survives; `main()` keeps fresh sessions and only vacuums when it deleted something; dependent-table cases iterate the script's own `V2_DEPENDENT_TABLES` so a newly added table cannot slip through.

```bash
cd opencode/scripts && python3 -m unittest test_prune_sessions -v     # 17 tests, OK
```

The same command is now a step in CI's `test-custom-modules` job, so the suite actually runs on PRs instead of depending on memory.

**Known limitations (recorded, not fixed):**
- A session that is the parent of a still-active child can be pruned, orphaning the child (`parent_id` is not consulted). Low probability at a 168 h window; verify on the test host with the query in Phase 2.
- The schema mapping is hardcoded and only existence-checked, so a renamed dependent table would silently leak orphan rows (no data loss) rather than fail.
- `instruction_blob` is content-addressed and never pruned — an unbounded-growth concern for later, unchanged by this task.

---

## Phase 2 — Validate on servyy-test.lxd

Use the `servyy-branch-deploy` skill. The testing inventory does not enable `opencode`, so drive compose directly rather than the Ansible tag.

**Step 0: pre-flight facts to confirm on the test host** (each one guards data, not uptime)

Run these against the **test host's** pre-upgrade DB copy (the migration runs in place on first V2 boot, so take the copy from the running V1 container with the `sqlite3` backup API as in Task 5, not with `docker cp`):

```bash
# 1. Every legacy session must exist in session_v2 after migration. Anything else
#    is a session whose content the pruner would delete with no V2 copy behind it.
sqlite3 opencode.db "select count(*) from session s where not exists (select 1 from session_v2 v where v.id = s.id)"   # expect 0

# 2. time_updated must actually move on activity — the inactivity guard is vacuous if it does not.
sqlite3 opencode.db "select id, datetime(time_created/1000,'unixepoch') c, datetime(time_updated/1000,'unixepoch') u from session_v2 order by time_updated desc limit 5"
#    then use one of those sessions in the test web UI and re-run the query: time_updated must advance.

# 3. Parents whose children would outlive them (pruner does not consult parent_id).
sqlite3 opencode.db "select count(*) from session_v2 p where p.parent_id is null and p.time_updated < strftime('%s','now','-168 hours')*1000 and exists (select 1 from session_v2 c where c.parent_id = p.id and c.time_updated >= strftime('%s','now','-168 hours')*1000)"   # expect 0
```

All three must be 0 / confirmed before the pruner is allowed to run in production. If (1) is non-zero, do not deploy — the migration dropped sessions and the V1 DB copy is the only remaining source.

**Step 1: build/sync the branch config onto the test host**

```bash
# from the infra checkout on the laptop
rsync -a opencode/ servyy-test.lxd:/tmp/opencode-v2/opencode/
ssh servyy-test.lxd "mkdir -p /home/cda/servyy-container/opencode && cp -a /tmp/opencode-v2/opencode/scripts /tmp/opencode-v2/opencode/plugins /tmp/opencode-v2/opencode/docker-compose.yml /home/cda/servyy-container/opencode/"
```

**Step 2: bring it up with the V2 image**

```bash
ssh servyy-test.lxd "cd /home/cda/servyy-container/opencode && docker compose pull && docker compose up -d"
```

Expected: `2.1.2` pulled; container healthy within ~60 s (first boot on a migrated DB may take longer — raise `start_period` if it flaps).

**Step 3: verify V2 is actually up**

```bash
ssh servyy-test.lxd "docker exec opencode.web opencode --version"          # expect: opencode v2.1.2
ssh servyy-test.lxd "docker exec opencode.web sh -c 'curl -s -o /dev/null -w \"%{http_code}\n\" http://localhost:4096/health'"   # expect: 200
ssh servyy-test.lxd "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/info'"  # expect: JSON with version
ssh servyy-test.lxd "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/plugin'" # expect: both local plugins listed
ssh servyy-test.lxd "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/model' | head -c 300"
ssh servyy-test.lxd "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/mcp'"
```

Expected: version `2.1.2`; `/api/plugin` lists `superpowers.js` and `session-messaging.js` (this is the check that #11 is fixed); `/api/model` lists the opencode-go and bailian models; `/api/mcp` shows `circleci`, `chrome-devtools`, `docstash` connected (OAuth-dependent ones may need sign-in).

**Step 4: verify the pruner against real data**

```bash
# copy the migrated DB, then run the pruner against the COPY — never the live file
ssh servyy-test.lxd "docker exec opencode.web python3 -c \"import sqlite3 as s; a=s.connect('/root/.local/share/opencode/opencode.db'); b=s.connect('/root/dev/prune-copy.db'); a.backup(b); b.close(); a.close()\""
ssh servyy-test.lxd "docker exec opencode.web sh -c 'OPENCODE_DB=/root/dev/prune-copy.db OPENCODE_PRUNE_HOURS=0 python3 /scripts/prune-sessions.py; echo exit=\$?'"
ssh servyy-test.lxd "docker exec opencode.web rm -f /root/dev/prune-copy.db"
```

Expected: exit 0, log line naming `session_v2` and the dependent tables (not `session`).

**This is destructive, not a dry-run.** `OPENCODE_PRUNE_HOURS=0` deletes every session older than *now* — i.e. essentially all of them — plus their `tool-output/` files and snapshots. Run it **last** on the test host, on the copy above, and only after the Step 0 migration-fidelity checks have passed; never point it at a DB you still need (`OPENCODE_DB` is what redirects it; the default path is the live DB — `tool-output/` and `snapshot/` are still the test host's live dirs, which is fine there and never acceptable in production).

**Step 5: verify MCP + a real turn**

Open `https://opencode-test.servyy-test.lxd` (or the preview host per the skill) with the Basic-auth credentials, start a session, confirm: a model answers, `todowrite` is available (todo flag), `chrome-devtools_navigate_page` works (chromium still installed by `startup.sh`), and `session_list` is listed as a tool.

**Step 6: tear down**

```bash
ssh servyy-test.lxd "cd /home/cda/servyy-container/opencode && docker compose down"
```

---

## Phase 3 — Production deploy on codey

### Task 5: Pre-flight disk check, then back up the V1 database (must be an online `sqlite3` backup)

The in-place V2 migration plus the pruner's `VACUUM` both need working room, and codey had **2.7 GB free at 91 %** (#15) before this change:

```bash
ssh codey.lehel.xyz "df -h /"    # record the free-space figure in the history doc
```

If `Avail` is under ~2 GB, free space first. `docker image prune` is *not* the answer (the container's npm cache is already cleared weekly and old snapshots are pruned nightly). The honest option is to stop the container, `VACUUM` the V1 DB, then continue with this task:

```bash
ssh codey.lehel.xyz "docker stop opencode.web"
ssh codey.lehel.xyz "docker run --rm -v opencode_root:/data alpine sh -c 'apk add -q sqlite && sqlite3 /data/.local/share/opencode/opencode.db VACUUM;'"
ssh codey.lehel.xyz "docker start opencode.web"    # the backup below runs `docker exec`
```

Re-check `df -h /` after the vacuum and before continuing.

A live `docker cp` produces a corrupt file (#8) — use the backup API, then copy the finished file:

```bash
ssh codey.lehel.xyz 'sudo docker exec opencode.web python3 -c "
import sqlite3
src = sqlite3.connect(\"/root/.local/share/opencode/opencode.db\")
dst = sqlite3.connect(\"/root/oc.v1.pre-v2.db\")
src.backup(dst); dst.close(); src.close(); print(\"backup ok\")
" && sudo docker cp opencode.web:/root/oc.v1.pre-v2.db /home/cda/oc.v1.pre-v2.db && ls -la /home/cda/oc.v1.pre-v2.db'
```

Expected: `backup ok`, file ~150 MB. Verify integrity before proceeding:

```bash
ssh codey.lehel.xyz 'python3 -c "import sqlite3;print(sqlite3.connect(\"/home/cda/oc.v1.pre-v2.db\").execute(\"pragma integrity_check\").fetchone())"'
```

Expected: `('ok',)`.

### Task 6: Deploy

**Pre-pull the image first — this ordering matters:**

```bash
ssh codey.lehel.xyz "docker pull ghcr.io/anomalyco/opencode:2.1.2"
```

Reason: the `restart opencode container` handlers (fired by the `startup.sh` / config / AGENTS.md copy tasks) run **before** the `docker_service` recreate, so the host briefly runs the new `startup.sh` (`exec opencode serve`) against the **old V1 image**, which has no `serve` subcommand. That is a short crash/502 window — and it becomes permanent if the play dies between the handler and play 3. Pre-pulling does not remove the window, but it removes the pull from it and makes the whole sequence as short as possible; keep the play running to completion and do not abort it in between.

```bash
cd /home/cda/dev/infrastructure/container
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
```

With the new "Deploy OpenCode session pruner" task this tag is sufficient for everything under `opencode/scripts/` (startup.sh, opencode.json.template, AGENTS.md, prune-sessions.py).

Notes:
- `docker_service` runs `docker compose up -d` (`state: present`) so the new tag is pulled and the container is **recreated** — the `restart opencode container` handler alone would never switch images.
- The first V2 boot runs the in-place DB migration (#7); expect a slower start on a 150 MB DB. Watch `docker logs -f opencode.web` rather than redeploying on the first unhealthy reading — and do **not** bump `start_period` without re-checking the `2m` watchtower gate in Task 1.
- The first nightly prune after the upgrade could in principle be a one-way mass delete, so Task 5's backup is the only rollback and must not be skipped. Measured on codey after the migration: the DB holds only the last 7 days (116 sessions, oldest `time_created` 2026-10-15), so the run is a **no-op** — `no sessions idle for more than 168h, nothing to do`, exit 0. (The "~292 of 347 sessions" figure this plan quoted earlier came from a developer laptop's DB, not from codey.) Still run the pruner by hand once (Task 7) before the 04:00 schedule does it unattended.

### Task 7: Post-deploy verification

```bash
ssh codey.lehel.xyz "docker exec opencode.web opencode --version"                     # opencode v2.1.2
ssh codey.lehel.xyz "docker ps --filter name=opencode.web --format '{{.Status}}'"     # Up (healthy)
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'curl -s -o /dev/null -w \"%{http_code}\n\" http://localhost:4096/health'"   # 200
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/plugin'"
curl -s -o /dev/null -w '%{http_code}\n' https://code.lehel.xyz/health               # 401 (edge auth still on)
```

Browser check on `https://code.lehel.xyz`: Basic-auth prompt (authgate), then the V2 web UI loads, a session starts, a model responds.

API-consumer check — see "The API bridge" above. The bridge itself needs no change, but each
consumer must be verified end-to-end: one real `dontforget` extraction, one `job-search` run
(including its `GET /api/model` discovery), one `devhub` develop run. Before those clients are
migrated, the prompt call fails with 400 — that is the expected state, not a regression to chase.

API-consumer check (`job-search` and `devhub` both call this host — see Risks): with the `opencode.api_key` value used in `ansible/plays/roles/docker_service/templates/job-search/api.env.j2`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $KEY" https://code.lehel.xyz/api/model   # 200
curl -s -H "X-Api-Key: $KEY" https://code.lehel.xyz/api/model | head -c 300                     # model list, not an error body
```

Then run one real operation through each consumer that goes over that API (a job-search model discovery/run, and a devhub dispatch) and confirm it succeeds rather than erroring on a missing/changed endpoint.

Session-messaging check (the regression this fixes): from a session on codey run `session_list` — it must appear in the tool list and return the registry.

Pruner check:

```bash
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'python3 /scripts/prune-sessions.py; echo exit=\$?'"
```

Expected: exit 0, log mentions `session_v2`.

### Task 8: Document

Add `history/2026-10-21_opencode-v2-upgrade.md` in ADR form (Context / Decision / Consequences / Implementation Details with commit hashes and the verification output / Known issues). Include the two gotchas worth remembering: `:latest` was the V1 line, and a live `docker cp` of the SQLite DB is corrupt.

---

## Rollback

1. `git revert` the compose commit (or set `image: ghcr.io/anomalyco/opencode:1.19.3` — the tag exists, so pin the exact V1 version instead of `:latest`).
2. Restore the DB **before** starting V1, because V2-written sessions live only in `session_v2`:

```bash
ssh codey.lehel.xyz "docker compose -f /home/cda/servyy-container/opencode/docker-compose.yml stop opencode"
ssh codey.lehel.xyz "docker run --rm -v opencode_root:/data -v /home/cda:/backup alpine sh -c 'cd /data/.local/share/opencode && rm -f opencode.db opencode.db-wal opencode.db-shm && cp /backup/oc.v1.pre-v2.db opencode.db'"
ssh codey.lehel.xyz "cd /home/cda/servyy-container/opencode && docker compose up -d"
```

3. After a rollback to V1, the **V2 pruner now deployed by the Ansible role** will exit 1 on the V1 schema instead of pruning — that failure is intended (it refuses to guess), but it means the nightly 04:00 job logs an error and nothing is pruned. Restore the pre-upgrade `prune-sessions.py` on the host alongside the DB restore (`opencode/scripts/` is bind-mounted, so the file swap takes effect on the next Ofelia run).

4. The two local plugins stay on their V2 ports (they were already V2 before this change — rolling back to V1 keeps session messaging broken, as today). If that must be restored, redeploy the pre-`6658674` (setup-home) copies.

## Risks

| Risk | Mitigation |
|---|---|
| V1 web UI bookmarks / clients that speak the V1 API break | the V1 API has **two in-cluster consumers**, not just the healthcheck: `job-search` and `devhub` both set `OPENCODE_BASE_URL=https://code.lehel.xyz` (`ansible/plays/roles/docker_service/templates/job-search/api.env.j2`, `.../devhub/web.env.j2`) and call `/api/model` / `/api/session*` — job-search with an API key (`OPENCODE_API_KEY`, via the `opencode-apikey-code` router in `traefik/dynamic.yaml`), devhub with Basic auth (`OPENCODE_BASIC_USER`/`OPENCODE_BASIC_PASSWORD`). Both are smoke-tested in Task 7; a browser client that speaks V1 is out of our control |
| First boot migration on a 150 MB DB takes longer than the healthcheck window | raise `start_period`; verify with `docker logs` before declaring failure |
| `provider`/`mcp` V1 shapes behave subtly differently in V2 (e.g. per-model `options.thinking` on bailian) | covered by Task 7 model checks; fix in a follow-up config conversion if needed |
| Todos / `external_directory` default changes alter agent behaviour | `experimental.todo: true` added; permission default accepted deliberately (Phase 0) |
| `opencode-working-memory` disappears | replaced by the V2-native global `AGENTS.md` channel (Task 3b); durable facts are curated, not auto-captured — accepted in Phase 0 |
| A later 2.x minor changes plugin/server behaviour again | Renovate keeps automerging minor/patch by owner decision; the container is pinned, so every bump is a reviewable PR and a fresh, revertible deploy |

## Outcome (executed 2026-10-22)

The upgrade ran on `servyy-test.lxd` first and then on codey. Verified results, the two
corrections to this plan (production session count, stale plugin file on the test host) and the
API-bridge smoke test are recorded in `history/2026-10-22_opencode-v2-upgrade.md`.

---

## Out of scope

- Converting `opencode.json` to the native V2 shape (`providers`, `mcp.servers`, ordered `permissions`) — explicitly optional per the migration guide.
- Automatic memory capture (e.g. `@mathew-cf/opencode-memory`). The pre-vetted fallback, to be benchmarked against codey's 1.9 GB RAM if curated `AGENTS.md` memory proves insufficient.
- `claude-hub` (disabled service sharing `codey_dev_checkouts`).
