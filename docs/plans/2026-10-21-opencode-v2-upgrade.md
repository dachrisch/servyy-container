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

## Phase 0 — Decisions to confirm before starting

| Decision | Recommendation | Why |
|---|---|---|
| Image reference | pin `ghcr.io/anomalyco/opencode:2.1.2`, never `:latest` again | `latest` is the V1 line (#1/#2); a pinned tag makes Renovate and rollback meaningful |
| Renovate behaviour | add a `packageRule` for `ghcr.io/anomalyco/opencode` with `automerge: false` | V2 changed the plugin + server API; a weekend minor bump should be a reviewed PR, not an auto-merge |
| Memory plugin (`opencode-working-memory`) | **drop it** | V1-only (#12), no V2 release; revisit a replacement separately |
| Todos | add `"experimental": { "todo": true }` | V2 off by default (#14); codey sessions use `todowrite` (20 calls in the current DB) |
| `external_directory` permission | keep V2 default (allowed) | an `ask` rule on an unattended server stalls sessions; the container is already a sandbox |
| TUI config (`tui.json`) | stop deploying it; delete the file | V2 terminal config is `cli.json`; the container runs no TUI, so the file is dead weight |
| V1 config shapes (`provider`, `mcp`, models) | keep for this change, convert later | explicitly optional per the migration guide (#13); smaller blast radius |

**Critical decision:** is losing `opencode-working-memory` acceptable? If not, stop and evaluate a V2 replacement *before* the upgrade, because there is no version that runs on both.

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
      # V2 answers /health with 200 without auth; V1 answered 401 and this test
      # greps for the 401. Keep the probe auth-free so a rotated
      # OPENCODE_SERVER_PASSWORD cannot mask a dead server.
      test: ["CMD-SHELL", "curl -fsS -o /dev/null http://localhost:4096/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
```

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
  "plugins": [],
  "experimental": {
    "todo": true
  },
  "mcp": { ... unchanged ... },
  "provider": { ... unchanged ... }
}
```

Notes:
- `plugin` (string array with `opencode-working-memory@1.6.9`) becomes `plugins` (#13); the memory plugin is dropped (#12) and its durable-facts role moves to the global `AGENTS.md` in Task 3b. Local plugin files under `/root/.config/opencode/plugins` are auto-discovered and need no config entry.
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

```markdown
# Global instructions (codey.lehel.xyz)

This OpenCode server runs on `codey.lehel.xyz` as `opencode.web`, reachable at
https://code.lehel.xyz behind Basic auth, with the shared checkouts under `/root/dev`.

- Repos in `/root/dev` carry their own `AGENTS.md`; read those before changing code.
- Deployment changes go through the `infrastructure/container` repo and Ansible — no manual edits on the host.
- Verify with `docker ps --filter name=opencode.web` and `curl -s http://localhost:4096/health`.
- Session pruning runs nightly at 04:00 (Ofelia); logs land in `docker logs portainer.ofelia`.
```

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

The pruner deletes by table today: `part`, `message`, `session_message`, `session_input`, `session_context_epoch`, `todo`, `session_share` keyed by `session_id`, then `session` by `time_created`. Under V2 (#9) the live rows are `session_v2` + `session_message` (+ `session_pending`, `session_inbox`), and the legacy tables — if they still exist after a migration — are history, not live data.

**Step 1: write the failing test**

Create `opencode/scripts/test_prune_sessions.py` that builds a throwaway SQLite DB with the **V2** tables (`session_v2`, `session_message`, `session_inbox`, `session_pending`, `event`, `event_sequence`), inserts one old and one fresh session, runs `prune_sessions()`, and asserts:
- the old session is gone from `session_v2` and all its `session_message`/`session_inbox` rows are gone,
- the fresh session and its messages survive,
- a legacy-only `session`/`part` table (if present) is left untouched.

**Step 2: run it, watch it fail**

```bash
cd /home/cda/dev/infrastructure/container/opencode/scripts && python3 -m unittest test_prune_sessions -v
```

Expected: FAIL (`no such table: session` / assertion on missing deletes).

**Step 3: implement**

- Replace the table/column map with the V2 set, keeping the legacy names only in an *optional* cleanup list that is applied only when the table exists (`sqlite_master` check), e.g.:

```python
V2_DEPENDENT_TABLES = [
    ("session_message", "session_id"),
    ("session_inbox", "session_id"),
    ("session_pending", "session_id"),
    ("event", "aggregate_id"),
    ("event_sequence", "aggregate_id"),
]
V2_SESSION_TABLE = "session_v2"
LEGACY_TABLES = [("part", "session_id"), ("message", "session_id"), ("todo", "session_id"),
                 ("session_share", "session_id"), ("session_input", "session_id"),
                 ("session_context_epoch", "session_id")]
```

- Delete sessions from `session_v2` by `time_created < cutoff` (ms epoch — verified same unit), delete dependents, then legacy rows for the same ids **only if the table exists**.
- Leave `tool-output/` and `snapshot/` logic unchanged (#10).

**Step 4: run the test again**

```bash
cd /home/cda/dev/infrastructure/container/opencode/scripts && python3 -m unittest test_prune_sessions -v
```

Expected: PASS.

**Step 5: commit**

```bash
git add opencode/scripts/prune-sessions.py opencode/scripts/test_prune_sessions.py
git commit -m "fix(opencode): prune V2 session tables (session_v2/session_message)"
```

---

## Phase 2 — Validate on servyy-test.lxd

Use the `servyy-branch-deploy` skill. The testing inventory does not enable `opencode`, so drive compose directly rather than the Ansible tag.

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
ssh servyy-test.lxd "docker exec opencode.web sh -c 'OPENCODE_PRUNE_HOURS=0 python3 /scripts/prune-sessions.py; echo exit=\$?'"
```

Expected: exit 0, log line naming `session_v2` and the dependent tables (not `session`). This is a destructive dry-run on the test host only.

**Step 5: verify MCP + a real turn**

Open `https://opencode-test.servyy-test.lxd` (or the preview host per the skill) with the Basic-auth credentials, start a session, confirm: a model answers, `todowrite` is available (todo flag), `chrome-devtools_navigate_page` works (chromium still installed by `startup.sh`), and `session_list` is listed as a tool.

**Step 6: tear down**

```bash
ssh servyy-test.lxd "cd /home/cda/servyy-container/opencode && docker compose down"
```

---

## Phase 3 — Production deploy on codey

### Task 5: Back up the V1 database (must be an online `sqlite3` backup)

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

```bash
cd /home/cda/dev/infrastructure/container
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
```

Notes:
- `docker_service` runs `docker compose up -d` (`state: present`) so the new tag is pulled and the container is **recreated** — the `restart opencode container` handler alone would never switch images.
- The first V2 boot runs the in-place DB migration (#7); expect a slower start on a 150 MB DB. If the healthcheck flaps, bump `start_period` to `60s` and redeploy.

### Task 7: Post-deploy verification

```bash
ssh codey.lehel.xyz "docker exec opencode.web opencode --version"                     # opencode v2.1.2
ssh codey.lehel.xyz "docker ps --filter name=opencode.web --format '{{.Status}}'"     # Up (healthy)
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'curl -s -o /dev/null -w \"%{http_code}\n\" http://localhost:4096/health'"   # 200
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'curl -s -u opencode:\$OPENCODE_SERVER_PASSWORD http://localhost:4096/api/plugin'"
curl -s -o /dev/null -w '%{http_code}\n' https://code.lehel.xyz/health               # 401 (edge auth still on)
```

Browser check on `https://code.lehel.xyz`: Basic-auth prompt (authgate), then the V2 web UI loads, a session starts, a model responds.

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

3. The two local plugins stay on their V2 ports (they were already V2 before this change — rolling back to V1 keeps session messaging broken, as today). If that must be restored, redeploy the pre-`6658674` (setup-home) copies.

## Risks

| Risk | Mitigation |
|---|---|
| V1 web UI bookmarks / clients that speak the V1 API break | nothing on the host calls the V1 API except the healthcheck (fixed); clients are browsers and the V2-capable laptop CLI |
| First boot migration on a 150 MB DB takes longer than the healthcheck window | raise `start_period`; verify with `docker logs` before declaring failure |
| `provider`/`mcp` V1 shapes behave subtly differently in V2 (e.g. per-model `options.thinking` on bailian) | covered by Task 7 model checks; fix in a follow-up config conversion if needed |
| Todos / `external_directory` default changes alter agent behaviour | `experimental.todo: true` added; permission default accepted deliberately (Phase 0) |
| `opencode-working-memory` disappears | replaced by the V2-native global `AGENTS.md` channel (Task 3b); durable facts are curated, not auto-captured — accepted in Phase 0 |
| A later 2.x minor changes plugin/server behaviour again | Renovate keeps automerging minor/patch by owner decision; the container is pinned, so every bump is a reviewable PR and a fresh, revertible deploy |

## Out of scope

- Converting `opencode.json` to the native V2 shape (`providers`, `mcp.servers`, ordered `permissions`) — explicitly optional per the migration guide.
- Automatic memory capture (e.g. `@mathew-cf/opencode-memory`). The pre-vetted fallback, to be benchmarked against codey's 1.9 GB RAM if curated `AGENTS.md` memory proves insufficient.
- `claude-hub` (disabled service sharing `codey_dev_checkouts`).
