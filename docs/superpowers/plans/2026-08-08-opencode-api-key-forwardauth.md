# opencode API-key ForwardAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an automated client drive opencode's session/chat API via a static `X-Api-Key` header, without sharing the human operator's Basic Auth password and without any filesystem/shell/VCS/credential access.

**Architecture:** A new internal-only Caddy container (`opencode-authgate`) checks `X-Api-Key` via Traefik's `forwardAuth` middleware; on success it returns `Authorization: Basic <opencode creds>`, which Traefik injects onto the forwarded request. A new, narrowly-scoped Traefik router (labels on opencode's own compose file, matching only `/api/session` create + `/api/session/{id}/...`) is the only path this middleware applies to — everything else still falls through to opencode's existing Basic-Auth-protected catch-all router. The key is also mirrored into Vaultwarden via the existing generalized `vaultwarden` role.

**Tech Stack:** Ansible (`docker_service` role, `vaultwarden` role), Docker Compose, Traefik v3.6 (file provider + Docker provider), Caddy 2 (Caddyfile), git-crypt.

## Global Constraints

- Test on `servyy-test.lxd` before production; production (`lehel.xyz`) deployment requires explicit user approval — never assume it (CLAUDE.md).
- No direct server file edits/scp — all changes go through this git repo + Ansible (CLAUDE.md).
- `docker-compose.yml`, `*.yaml`, `*.env` files are git-crypt encrypted; edit them normally when the repo is unlocked (plaintext on disk), git-crypt handles encryption on commit.
- Never name a Docker Compose service `app` (DNS ambiguity) — this plan uses `authgate`.
- No new Molecule scenario needed: `opencode-authgate` reuses the existing generic `docker_service` role, which already has coverage; the new Caddy/Traefik logic is verified functionally with curl instead (per the approved spec, `docs/superpowers/specs/2026-08-08-opencode-api-key-forwardauth-design.md`).
- Commit messages: `<type>: <description>` (`feat`, `fix`, `chore`, `docs`).
- Two corrections to the approved spec, discovered while nailing down exact syntax (both harmless, noted for transparency):
  1. **Router location:** the spec said the new router would live in `traefik/dynamic.yaml`. That file is deployed byte-identical to every environment (prod/test/dev) with no per-host templating (confirmed: it's git-tracked directly, the only environment-specific mutation is a test-only `blockinfile` append for mkcert TLS certs — nothing router-related). A router needs a per-environment `Host()` rule, so it belongs as docker-compose labels on `opencode/docker-compose.yml` instead — exactly how every other router in this repo is already defined, reusing the already-per-host-correct `${SERVICE_HOST}`. Only the `forwardAuth` middleware *definition* (which has no per-host content — it just names the `opencode-authgate` container) stays in `dynamic.yaml`, matching how it already holds the one existing middleware (`crawler-ratelimit`).
  2. **Vaultwarden push guard:** the spec said production-only, but also said "matching `ls_dbeaver_access`'s guards" — which actually allows both `lehel.xyz` and `servyy-test.lxd`. Going with the latter (matching guard, not "production-only"): item names already include `{{ inventory_hostname_short }}`, so pushing from both hosts creates distinct, non-colliding items and lets the push mechanism itself be verified on test before trusting it on production.

---

### Task 1: Generate and store the API key secret

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`

**Interfaces:**
- Produces: `opencode.api_key` (Ansible var, available to any play that includes `vars/secrets.yml`) — a 64-character hex string.

- [ ] **Step 1: Generate the token**

```bash
openssl rand -hex 32
```

Copy the output (64 hex characters) — call it `<TOKEN>` below.

- [ ] **Step 2: Add it to secrets.yml**

Open `ansible/plays/vars/secrets.yml`. It currently has (around line 124):

```yaml
opencode:
  server_password: "pawing-thirsty-gumminess5-underwire-egomaniac"
```

Change it to:

```yaml
opencode:
  server_password: "pawing-thirsty-gumminess5-underwire-egomaniac"
  api_key: "<TOKEN>"
```

(with `<TOKEN>` replaced by the real generated value — this is a real secret, not a placeholder to fill in later).

- [ ] **Step 3: Confirm the file is still git-crypt-covered and valid YAML**

```bash
cd /home/cda/dev/infrastructure/container
git-crypt status ansible/plays/vars/secrets.yml
python3 -c "import yaml; yaml.safe_load(open('ansible/plays/vars/secrets.yml'))" && echo "YAML OK"
```

Expected: `encrypted: ansible/plays/vars/secrets.yml` and `YAML OK`.

- [ ] **Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add opencode.api_key secret for the ForwardAuth API-key gate"
```

---

### Task 2: Build and verify the `opencode-authgate` validator service in isolation

**Files:**
- Create: `opencode-authgate/docker-compose.yml`
- Create: `opencode-authgate/Caddyfile`
- Create: `ansible/plays/roles/docker_service/templates/opencode-authgate/.env.j2`
- Modify: `ansible/plays/user.yml`

**Interfaces:**
- Consumes: `opencode.api_key`, `opencode.server_password` (from Task 1 / existing secrets.yml)
- Produces: container `opencode-authgate.authgate`, reachable on the `proxy` Docker network at `http://opencode-authgate.authgate:80/`. On a request with header `X-Api-Key: <opencode.api_key>`, responds `200` with response header `Authorization: Basic <base64("opencode:" + opencode.server_password)>`. On any other request, responds `401`. No public route (`traefik.enable=false`).

- [ ] **Step 1: Create the compose file**

`opencode-authgate/docker-compose.yml`:

```yaml
services:
  authgate:
    image: caddy:2-alpine
    container_name: ${COMPOSE_PROJECT_NAME}.authgate
    restart: unless-stopped
    env_file:
      - .env
      - authgate.env
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
    networks:
      - proxy
    labels:
      - traefik.enable=false

networks:
  proxy:
    external: true
```

`traefik.enable=false` is required, not optional: `traefik/traefik.yaml` sets `providers.docker.exposedByDefault: true`, so without this label Traefik would try to auto-expose this container too.

- [ ] **Step 2: Create the Caddyfile**

`opencode-authgate/Caddyfile`:

```
{
	auto_https off
}

:80 {
	@valid_key {
		header X-Api-Key {$OPENCODE_API_KEY}
	}

	handle @valid_key {
		header Authorization "Basic {$OPENCODE_BASIC_AUTH_B64}"
		respond 200
	}

	handle {
		respond 401
	}
}
```

No secrets in this file — `{$VAR}` is Caddy's own environment-variable substitution, filled in from `authgate.env` at container start. Consecutive `handle` blocks are mutually exclusive and evaluated in order (Caddy's standard idiom for "if matched do X, else do Y").

- [ ] **Step 3: Create the env template**

`ansible/plays/roles/docker_service/templates/opencode-authgate/.env.j2`:

```
OPENCODE_API_KEY={{ opencode.api_key }}
OPENCODE_BASIC_AUTH_B64={{ ('opencode:' + opencode.server_password) | b64encode }}
```

- [ ] **Step 4: Wire the role invocation**

In `ansible/plays/user.yml`, immediately after the existing `opencode` block (ends at line 116, right before the `energy` block), insert:

```yaml
    - role: docker_service
      vars:
        service_dir: opencode-authgate
        env_templates:
          - src: docker.env.j2
            dest: .env
          - src: opencode-authgate/.env.j2
            dest: authgate.env
      tags: [user.docker, user.docker.opencode-authgate]
```

- [ ] **Step 5: Syntax-check**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```

Expected: no errors.

- [ ] **Step 6: Deploy to servyy-test**

```bash
cd ansible && ./servyy-test.sh --tags "user.repo,user.docker.opencode-authgate,user.docker.env"
```

Expected: `PLAY RECAP` shows `failed=0 unreachable=0`.

- [ ] **Step 7: Verify the container is healthy**

```bash
ssh servyy-test.lxd "docker ps | grep opencode-authgate"
ssh servyy-test.lxd "docker logs opencode-authgate.authgate --tail 20"
```

Expected: container `Up`, logs show Caddy's normal startup (no config-parse errors).

- [ ] **Step 8: Verify the auth logic directly (bypassing Traefik)**

```bash
AUTHGATE_IP=$(ssh servyy-test.lxd "docker inspect -f '{{.NetworkSettings.Networks.proxy.IPAddress}}' opencode-authgate.authgate")
REAL_KEY=$(ssh servyy-test.lxd "grep OPENCODE_API_KEY /home/cda/servyy-container/opencode-authgate/authgate.env | cut -d= -f2")

# No key -> 401
ssh servyy-test.lxd "curl -s -o /dev/null -w '%{http_code}\n' http://$AUTHGATE_IP/api/session -X POST"

# Wrong key -> 401
ssh servyy-test.lxd "curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Api-Key: wrong' http://$AUTHGATE_IP/api/session -X POST"

# Correct key -> 200 + Authorization response header present
ssh servyy-test.lxd "curl -sD - -o /dev/null -H 'X-Api-Key: $REAL_KEY' http://$AUTHGATE_IP/api/session -X POST"
```

Expected: first two print `401`; the third prints `HTTP/1.1 200 OK` with an `Authorization: Basic ...` header in the response.

- [ ] **Step 9: Commit**

```bash
git add opencode-authgate/ ansible/plays/roles/docker_service/templates/opencode-authgate/.env.j2 ansible/plays/user.yml
git commit -m "feat: add opencode-authgate Caddy service for API-key validation"
```

---

### Task 3: Wire Traefik routing and verify end-to-end on servyy-test

**Files:**
- Modify: `traefik/dynamic.yaml`
- Modify: `opencode/docker-compose.yml`

**Interfaces:**
- Consumes: `opencode-authgate.authgate:80` (Task 2's container, internal DNS name)
- Produces: Traefik middleware `opencode-apikey-auth@file`; router `${SERVICE_NAME}_apikey` on the `opencode` container matching `POST /api/session` and any `/api/session/{id}/...` path (except `/api/session/active`), gated by that middleware.

- [ ] **Step 1: Add the forwardAuth middleware**

In `traefik/dynamic.yaml`, add alongside the existing `crawler-ratelimit` middleware:

```yaml
http:
  middlewares:
    crawler-ratelimit:
      rateLimit:
        average: 10
        period: 1s
        burst: 20
        sourceCriterion:
          requestHeaderName: User-Agent
    opencode-apikey-auth:
      forwardAuth:
        address: "http://opencode-authgate.authgate:80/"
        authResponseHeaders:
          - "Authorization"
```

- [ ] **Step 2: Add the scoped router to opencode's own compose labels**

In `opencode/docker-compose.yml`, in the existing `labels:` block, add (after the existing `_local_qualified` labels, before the `watchtower` label):

```yaml
      - "traefik.http.routers.${SERVICE_NAME}_apikey.rule=Host(`${SERVICE_HOST}`) && ((Path(`/api/session`) && Method(`POST`)) || (PathPrefix(`/api/session/`) && !PathPrefix(`/api/session/active`)))"
      - traefik.http.routers.${SERVICE_NAME}_apikey.entrypoints=websecure
      - traefik.http.routers.${SERVICE_NAME}_apikey.tls.certresolver=letsencryptdnsresolver
      - traefik.http.routers.${SERVICE_NAME}_apikey.service=${SERVICE_NAME}
      - traefik.http.routers.${SERVICE_NAME}_apikey.middlewares=opencode-apikey-auth@file
      - traefik.http.routers.${SERVICE_NAME}_apikey.priority=100
```

The `@file` suffix is required — it's how a docker-provider-discovered router references a middleware defined in the file provider (`dynamic.yaml`); without it Traefik looks for a middleware named `opencode-apikey-auth` inside the Docker provider's own namespace and won't find it.

- [ ] **Step 3: Syntax-check**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```

- [ ] **Step 4: Deploy to servyy-test**

```bash
cd ansible && ./servyy-test.sh --tags "user.repo,user.docker.traefik,user.docker.opencode,user.docker.env"
```

`traefik/traefik.yaml` has `providers.file.watch: true`, so Traefik hot-reloads `dynamic.yaml` — no manual restart needed, but redeploying `user.docker.opencode` recreates the `opencode` container so its new labels take effect.

- [ ] **Step 5: Verify end-to-end via the public test hostname**

```bash
REAL_KEY=$(ssh servyy-test.lxd "grep OPENCODE_API_KEY /home/cda/servyy-container/opencode-authgate/authgate.env | cut -d= -f2")

# No key on the API path -> 401
curl -sk -o /dev/null -w '%{http_code}\n' https://opencode.servyy-test.lxd/api/session -X POST

# Correct key, allowed path -> 200 (or whatever opencode itself returns for a valid create), NOT opencode's own 401
curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" https://opencode.servyy-test.lxd/api/session -X POST

# Correct key, blocked paths (filesystem, shell/PTY, VCS, project, credentials) -> 401 each
# (falls through to opencode's own Basic Auth, no key accepted there)
for path in /api/fs/list /api/pty /vcs /project /api/credential/x; do
  echo -n "$path -> "
  curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" "https://opencode.servyy-test.lxd$path"
done

# Correct key, blocked path (session listing) -> 401
curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" https://opencode.servyy-test.lxd/api/session

# Human web UI unaffected -> 401 with Basic realm challenge, unrelated to the API key
curl -sk -I https://opencode.servyy-test.lxd/ | grep -i www-authenticate
```

Expected: `401`, `200`-range, `401` for every path in the loop, `401` for bare session-listing, and a `WWW-Authenticate: Basic realm="Secure Area"` line respectively. If the create-session check doesn't come back in the 200 range, check `ssh servyy-test.lxd "docker logs opencode.web --tail 20"` — a mismatched `OPENCODE_BASIC_AUTH_B64` (wrong password encoded, or missing `opencode:` prefix) is the most likely cause.

- [ ] **Step 6: Commit**

```bash
git add traefik/dynamic.yaml opencode/docker-compose.yml
git commit -m "feat: scope a Traefik ForwardAuth router to opencode's session API"
```

---

### Task 4: Push the API key to Vaultwarden and verify on servyy-test

**Files:**
- Create: `ansible/plays/opencode_authgate.yml`
- Modify: `ansible/servyy.yml`

**Interfaces:**
- Consumes: `vaultwarden` role's `push_items.yml` task (existing, `ansible/plays/roles/vaultwarden/`), `opencode.api_key` (Task 1)
- Produces: a Bitwarden Login item per host named `opencode api key (<inventory_hostname_short>)`, username `opencode`, password = the API key.

- [ ] **Step 1: Create the play**

`ansible/plays/opencode_authgate.yml`:

```yaml
---
- name: Push opencode API key to Vaultwarden
  hosts: all
  strategy: linear
  remote_user: "{{ create_user }}"
  become: true
  become_user: "{{ create_user }}"
  vars_files:
    - vars/default.yml
    - vars/secrets.yml
  vars_prompt:
    - name: vw_master_password
      prompt: "Vaultwarden master password (enter to skip opencode API key backup copy)"
      private: true
      default: ""
      confirm: false
  tasks:
    - name: Push opencode API key into Vaultwarden
      include_role:
        name: vaultwarden
        tasks_from: push_items.yml
        apply:
          tags:
            - opencode.vaultwarden
      vars:
        vaultwarden_item_username: "opencode"
        vaultwarden_items:
          - name: "opencode api key ({{ inventory_hostname_short }})"
            secret: "{{ opencode.api_key }}"
            notes: >-
              X-Api-Key value for opencode's scoped ForwardAuth gate (opencode-authgate) on
              {{ inventory_hostname }}. Grants session-create + session-scoped chat access to
              /api/session/* only, via https://opencode.{{ inventory_hostname }} — no
              filesystem, shell/PTY, VCS, project, or credential-management access. See
              docs/superpowers/specs/2026-08-08-opencode-api-key-forwardauth-design.md.
      when:
        - vw_master_password | default('') | length > 0
        - inventory_hostname in ['lehel.xyz', 'servyy-test.lxd']
      tags:
        - opencode.vaultwarden
  tags:
    - opencode.vaultwarden
```

- [ ] **Step 2: Import it from servyy.yml**

In `ansible/servyy.yml`, immediately after `- import_playbook: plays/user.yml`, add:

```yaml
- import_playbook: plays/opencode_authgate.yml
```

- [ ] **Step 3: Syntax-check**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```

- [ ] **Step 4: Run against servyy-test**

```bash
cd ansible && ansible-playbook servyy.yml -i testing --tags opencode.vaultwarden --limit servyy-test.lxd
```

This prompts interactively for the Vaultwarden master password — run it from an interactive terminal, not backgrounded/non-interactively. Entering nothing skips the push (exit 0, no changes) — that's a valid outcome if you don't have the master password to hand right now, but the push itself needs to be exercised at least once to consider this task done.

- [ ] **Step 5: Verify the item exists**

Log into `https://pass.lehel.xyz` (Vaultwarden web UI) and confirm a Login item named `opencode api key (servyy-test)` exists with username `opencode` and the password matching Task 1's generated token.

- [ ] **Step 6: Commit**

```bash
git add ansible/plays/opencode_authgate.yml ansible/servyy.yml
git commit -m "feat: mirror the opencode API key into Vaultwarden"
```

---

### Task 5: Production deployment (requires explicit user approval)

**Files:** none — this task only runs the automation already built and tested in Tasks 1-4, against `lehel.xyz`.

**Interfaces:** none new.

- [ ] **Step 1: Push the branch**

```bash
git push origin claude/opencode-api-key-forwardauth
```

- [ ] **Step 2: Stop and ask the user**

Per this repo's CLAUDE.md mandatory rule, do not proceed past this point without the user explicitly approving a production deployment. Show them: the branch name, the four commits, and the servyy-test verification results from Tasks 2-4 (Step 8 in Task 2, Step 5 in Task 3, Step 5 in Task 4). Ask: "Should I deploy this to production (`lehel.xyz`)?"

- [ ] **Step 3: Merge and deploy (only after approval)**

```bash
git checkout master
git merge --ff-only claude/opencode-api-key-forwardauth   # fast-forward only, per this workstation's known git-merge quirk
git push origin master
cd ansible && ./servyy.sh --tags "user.repo,user.docker.opencode-authgate,user.docker.traefik,user.docker.opencode,user.docker.env"
```

- [ ] **Step 4: Verify against production**

Repeat Task 3 Step 5's curl matrix against `https://opencode.lehel.xyz` instead of `opencode.servyy-test.lxd` (drop `-k`, production has a real Let's Encrypt cert).

- [ ] **Step 5: Push the key to Vaultwarden from production**

```bash
cd ansible && ansible-playbook servyy.yml --tags opencode.vaultwarden --limit lehel.xyz
```

Confirm a second Login item, `opencode api key (lehel)`, appears in Vaultwarden alongside the servyy-test one.

- [ ] **Step 6: Hand the key to the client**

Give the operator/process that will call the API the value of `opencode.api_key` from `secrets.yml` (or the Vaultwarden item) out-of-band, along with the header name (`X-Api-Key`) and base URL (`https://opencode.lehel.xyz/api/session`).
