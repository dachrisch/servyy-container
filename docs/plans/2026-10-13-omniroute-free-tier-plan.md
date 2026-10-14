# OmniRoute Free-First Tier Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an OmniRoute sidecar to the codey opencode service so sessions default to pooled free models and paid providers stay explicit user choice.

**Architecture:** One new `omniroute` container in `opencode/docker-compose.yml` (localhost `:20128` only, no Traefik), one new provider block in `opencode.json.template`, secrets via git-crypt `secrets.yml` → `opencode/.env.j2`. Full design: `docs/plans/2026-10-13-omniroute-free-tier-design.md`.

**Tech Stack:** Ansible (docker_service + opencode roles), Docker Compose, OmniRoute (`diegosouzapw/omniroute`, pinned tag resolved in Task 5), Molecule fixtures, git-crypt secrets.

**Constraints (do not violate):**
- Test-first: Molecule fixtures before templates (AGENTS.md).
- NEVER commit unencrypted secrets; run `git-crypt status` before every commit.
- NEVER include `ansible/plays/roles/user/defaults/main.yaml` (0-byte worktree quirk, pre-existing) in any commit.
- No OAuth/cookie provider vars anywhere. No MCP/A2A. No Traefik router for OmniRoute.
- Molecule scenario is unrunnable on the controller (no Docker daemon — precedent in `history/2026-09-26_opencode-working-memory.md`): validate fixtures by lint + parse, prove by live test deploy.

---

### Task 1: Molecule converge fixture — test OmniRoute key

**Files:**
- Modify: `ansible/plays/roles/docker_service/molecule/default/converge.yml:18-28` (opencode vars block)

**Step 1: Write the failing test (fixture first)**

Add to the `opencode:` vars block, after `opencode_go_api_key`:
```yaml
      omniroute_api_key: test-omniroute-api-key
```

**Step 2: Run lint + parse to verify fixtures still valid**

Run: `yamllint -c ../../../../.yamllint.yml molecule/default/converge.yml` from `ansible/plays/roles/docker_service`
Expected: clean (no output). Note path: repo-root `.yamllint.yml`; adjust relative path to reach it.

Run: `python3 -c "import yaml; d=yaml.safe_load(open('molecule/default/converge.yml')); print(d[0]['vars']['opencode']['omniroute_api_key'])"` from `ansible/plays/roles/docker_service`
Expected: `test-omniroute-api-key`

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/molecule/default/converge.yml
git-crypt status --fix 2>/dev/null; git-crypt status | head -5
git commit -m "test: add omniroute test key to docker_service converge fixture"
```
Expected: commit succeeds, `git-crypt status` shows no unencrypted secret files staged. Verify `git status --short` does NOT list `ansible/plays/roles/user/defaults/main.yaml` among staged files before committing.

---

### Task 2: Molecule verify — assert new env var, forbid OAuth/cookie vars

**Files:**
- Modify: `ansible/plays/roles/docker_service/molecule/default/verify.yml` (after the `GIT_CRYPT_KEY_B64` block, ~line 162)

**Step 1: Write the failing assertions**

```yaml
    - name: Verify opencode.env carries OMNIROUTE_API_KEY
      ansible.builtin.command:
        cmd: grep -q '^OMNIROUTE_API_KEY=test-omniroute-api-key$' /home/molecule/opencode/opencode.env
      changed_when: false

    - name: Verify opencode.env carries no OAuth/cookie provider vars
      ansible.builtin.command:
        cmd: grep -qiE 'oauth|cookie' /home/molecule/opencode/opencode.env
      register: oauth_cookie_present
      changed_when: false
      failed_when: oauth_cookie_present.rc == 0
```

**Step 2: Run lint + parse**

Run: `yamllint` on `verify.yml` (same form as Task 1) — Expected: clean.
Run: `python3 -c "import yaml; yaml.safe_load(open('molecule/default/verify.yml')); print('ok')"` — Expected: `ok`.

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/molecule/default/verify.yml
git commit -m "test: verify OMNIROUTE_API_KEY present, OAuth/cookie vars absent"
```

---

### Task 3: Render the secret — `opencode/.env.j2`

**Files:**
- Modify: `ansible/plays/roles/docker_service/templates/opencode/.env.j2` (append after line 6)

**Step 1: Confirm the test fails (template lacks the var)**

Run: `grep -q '^OMNIROUTE_API_KEY=' ansible/plays/roles/docker_service/templates/opencode/.env.j2; echo "rc=$?"` from repo root
Expected: `rc=1` (absent — this is the red state).

**Step 2: Minimal implementation**

Append:
```
OMNIROUTE_API_KEY={{ opencode.omniroute_api_key }}
```

**Step 3: Verify green**

Run: `grep -q '^OMNIROUTE_API_KEY={{ opencode.omniroute_api_key }}$' ansible/plays/roles/docker_service/templates/opencode/.env.j2 && echo PASS` — Expected: `PASS`.
Run: `yamllint -c .yamllint.yml ansible/plays/roles/docker_service/templates/opencode/.env.j2` — Expected: clean (dotenv `.j2` noise is pre-existing per history; no NEW warnings vs before).

**Step 4: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/opencode/.env.j2
git commit -m "feat: render OMNIROUTE_API_KEY into opencode.env"
```

---

### Task 4: `startup.sh` — extend the envsubst allowlist

**Files:**
- Modify: `opencode/scripts/startup.sh:68`

**Step 1: Red state**

Run: `grep -q 'OMNIROUTE_API_KEY' opencode/scripts/startup.sh; echo "rc=$?"` — Expected: `rc=1`.

**Step 2: Minimal implementation**

Change line 68 from:
```sh
    envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY $OPENCODE_GO_API_KEY' < /scripts/opencode.json.template > "$CONFIG_DIR/opencode.json"
```
to:
```sh
    envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY $OPENCODE_GO_API_KEY $OMNIROUTE_API_KEY' < /scripts/opencode.json.template > "$CONFIG_DIR/opencode.json"
```

**Step 3: Verify**

Run: `sh -n opencode/scripts/startup.sh && echo PASS` — Expected: `PASS`.

**Step 4: Commit**

```bash
git add opencode/scripts/startup.sh
git commit -m "feat: pass OMNIROUTE_API_KEY through opencode config render"
```

---

### Task 5: `opencode.json.template` — free-first provider + models

**Files:**
- Modify: `opencode/scripts/opencode.json.template:24-67` (provider block)

**Step 1: Red state**

Run: `python3 -c "import json; print('omniroute' in json.load(open('opencode/scripts/opencode.json.template'))['provider'])"` — Expected: `False`.

**Step 2: Minimal implementation**

Inside `"provider"`, after the `"opencode-go"` block (lines 25–29), insert:
```json
    "omniroute": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "OmniRoute Free Pool",
      "options": {
        "baseURL": "http://localhost:20128/v1",
        "apiKey": "$OMNIROUTE_API_KEY"
      },
      "models": {
        "omniroute-auto": {
          "name": "OmniRoute Auto (free first)"
        },
        "omniroute-cheap": {
          "name": "OmniRoute Cheap (free first)"
        },
        "omniroute-coding": {
          "name": "OmniRoute Coding (free first)"
        }
      }
    },
```
Model IDs map to upstream combos (`auto`, `auto/cheap`, `auto/coding`) at the gateway; the template only names them. If the gateway's combo IDs differ at implementation time, adjust the keys and note the mapping in the commit message.

**Step 3: Verify render + parse**

Run:
```bash
export CIRCLECI_TOKEN=t CIRCLECI_BASE_URL=https://circleci.com DASHSCOPE_API_KEY=t OPENCODE_GO_API_KEY=t OMNIROUTE_API_KEY=t
envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY $OPENCODE_GO_API_KEY $OMNIROUTE_API_KEY' < opencode/scripts/opencode.json.template | python3 -m json.tool > /dev/null && echo PASS
```
Expected: `PASS` (valid JSON after substitution, `$schema` intact).

**Step 4: Commit**

```bash
git add opencode/scripts/opencode.json.template
git commit -m "feat: add omniroute free-first provider to opencode config"
```

---

### Task 6: `docker-compose.yml` — OmniRoute sidecar

**Files:**
- Modify: `opencode/docker-compose.yml` (services + volumes)

**Step 1: Resolve the pinned image tag (no guessing)**

Run: look up the latest stable release of `diegosouzapw/omniroute` (Docker Hub / GitHub releases) at implementation time and record tag + digest in the commit message. Do NOT use `:latest`.

**Step 2: Minimal implementation**

Append service (after the `opencode` service, before top-level `volumes:`):
```yaml
  omniroute:
    image: diegosouzapw/omniroute:<PINNED_TAG>
    container_name: opencode.omniroute
    restart: unless-stopped
    env_file:
      - .env
      - opencode.env
    volumes:
      - omniroute_data:/data
    networks:
      - proxy
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O /dev/null http://localhost:20128/v1/models || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    labels:
      - com.centurylinklabs.watchtower.scope=prod
```
And under top-level `volumes:` add:
```yaml
  omniroute_data:
```
Notes: no Traefik labels (localhost only). No ports published (opencode.web reaches it over the shared `proxy` network … if the gateway binds only loopback inside its own netns, `opencode.web` CANNOT reach it — verify at test-deploy time: if unreachable, add `expose: ["20128"]` (compose-network visible, still no host publish) and keep `baseURL: http://omniroute:20128/v1` as fallback; record the working form in the commit. State path `/data`: confirm against the image docs at implementation time; adjust the volume target if the image uses a different path.

**Step 3: Verify**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('opencode/docker-compose.yml')); print(sorted(d['services'].keys())); print(sorted(d['volumes'].keys()))"` — Expected: services include `omniroute`, volumes include `omniroute_data`.
Run: `yamllint -c .yamllint.yml opencode/docker-compose.yml` — Expected: clean.
If `docker` binary exists: `docker compose -f opencode/docker-compose.yml config --quiet && echo PASS` (informational; daemon not required for config check).

**Step 4: Commit**

```bash
git add opencode/docker-compose.yml
git commit -m "feat: add omniroute sidecar to opencode compose (localhost only)"
```

---

### Task 7: Pre-commit validation gate (all playbooks + lint)

**Files:** none (verification only)

**Step 1: Run the gate**

```bash
git-crypt status | head -5
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/user.yml --syntax-check -i testing
cd ansible && yamllint -c ../.yamllint.yml .
```
Expected: `git-crypt status` clean; both syntax checks pass; yamllint shows only pre-existing dotenv `.j2` noise (compare against master if unsure: `git stash -u` is FORBIDDEN here — instead `git diff master --stat` to confirm only intended files changed).

**Step 2: Confirm change set is exactly the intended files**

Run: `git status --short && git diff master --stat` from repo root
Expected: modified = converge.yml, verify.yml, `.env.j2`, startup.sh, opencode.json.template, docker-compose.yml (+ the two plan docs untracked). `ansible/plays/roles/user/defaults/main.yaml` MUST NOT be staged; if it shows `M`, leave it unstaged.

---

### Task 8: Store the gateway secret (encrypted)

**Files:**
- Modify: `ansible/plays/vars/secrets.yml` (git-crypt encrypted, `opencode:` block ~line 126)

**Step 1: Generate a value (local gateway auth only — keyless pool needs no upstream keys in v1)**

Run: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` and use the output as the value. (If the pinned image documents keyless operation with no auth, keep the var anyway for forward-compat — the template already references it.)

**Step 2: Edit ONLY via an unlocked checkout**

Add under `opencode:`:
```yaml
  omniroute_api_key: "<generated>"
```
Verify with `git-crypt status` that the file still shows `encrypted`. NEVER paste the value into chat, plan docs, or commit messages.

**Step 3: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git-crypt status
git commit -m "feat: add opencode.omniroute_api_key secret"
```

---

### Task 9: Test deploy on servyy-test.lxd + smokes

**Files:** none (deployment + verification)

**Step 1: Deploy scoped**

Run: `ansible-playbook servyy.yml -i testing --tags user.docker.opencode` from `ansible/`
Expected: no failures (precedent: ok=52/failed=0 shape; exact count may differ after fixture changes).

**Step 2: Gateway smoke (on the test host)**

- `curl -s http://localhost:20128/v1/models | head -c 500` → model list, exit 0.
- `docker ps | grep omniroute` → `opencode.omniroute` Up + healthy.
- From inside `opencode.web`: reachability of the gateway baseURL form chosen in Task 6 (fix Task 6 form here if unreachable — amend that commit, do not layer hacks).

**Step 3: Config smoke**

- Rendered `/root/.config/opencode/opencode.json` inside the container contains the `omniroute` provider and 3 models; `opencode models` lists `omniroute-auto/cheap/coding`.
- Free-model inference probe succeeds; `bailian-payg` control probe still succeeds; `memory-diag` OK (no 403 regression).

**Step 4: Record results** in the test section of the design doc follow-up or commit message. Do not proceed to Task 10 on any red smoke.

---

### Task 10: Prod deploy on codey + soak criteria

**Files:** none (deployment + verification)

**Step 1: Deploy scoped to prod**

Run the standard prod path for this tag (same scope as history: `./servyy.sh`-style run limited to `codey.lehel.xyz` with `--tags user.docker.opencode`; use the repo's documented prod command at implementation time).
Expected: play passes; `healthy`; 0 ERROR lines since boot in `opencode.web` logs.

**Step 2: Prod smokes** — repeat Task 9 steps 2–3 against codey.

**Step 3: Soak (1 week, free-first default)**

- Dashboard/usage shows free-pool drain before any paid tokens.
- No 403-class errors; memory still extraction-at-compaction only.
- Rollback if red: remove provider block + sidecar, redeploy same tag (single-tag revert, documented in design doc).

---

## Execution Handoff

Branch `claude/omniroute-free-tier` already exists off `72baf4f` (origin/master). Molecule fixtures are Tasks 1–2 (test-first). Secrets in Task 8 stay encrypted. Test env carries no provider keys by design — keyless pool is what makes the test deploy meaningful without upstream accounts.
