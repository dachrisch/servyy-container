# OpenCode Dev-Checkout Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OpenCode container (`opencode.web` on lehel.xyz) self-provision its `/root/dev` git checkouts and the credentials they need (GitHub PAT for HTTPS clone/push, an SSH key for `servy.lehel.xyz`, and a git-crypt unlock of the infra repo) on every boot, so a volume rebuild self-heals instead of losing the working environment.

**Architecture:** Secrets and a declared repo list live in `ansible/plays/vars/secrets.yml` (git-crypt encrypted) and are rendered into `opencode/opencode.env` via the existing `docker_service` env-template mechanism. A new idempotent script `opencode/scripts/provision-dev.sh` — invoked from the existing declarative `startup.sh` on every container boot — writes the SSH key + git credential helper, clones/pulls the declared repos into `/root/dev`, and `git-crypt unlock`s the infra checkout. The container reaches the host over the internal docker bridge (`host.docker.internal` → host-gateway), and its SSH public key is authorized on the `cda` user of lehel.xyz **restricted to local docker networks** (`from="172.16.0.0/12,127.0.0.1"`) via a new Ansible task.

**Tech Stack:** Ansible, Docker Compose, git-crypt, POSIX sh (the opencode image is Alpine/BusyBox + bun), Python 3 (installed by `startup.sh`), Molecule (docker_service scenario).

## Global Constraints

- **Test-first:** every change is validated on `servyy-test.lxd` before production — no exceptions (CLAUDE.md).
- **Explicit prod approval:** never deploy to `lehel.xyz` without the user saying so.
- **No plaintext secrets in git:** PAT, git-crypt key, SSH private key go only into `ansible/plays/vars/secrets.yml` (git-crypt encrypted, matches `secrets.*` pattern). Never write real secret values into this plan, into `docs/`, or into any non-encrypted file.
- **Service name rule:** never introduce a docker-compose service named `app`.
- **Branch discipline:** work on a `claude/*` branch; prod branch must be `master` after rollout.
- **Commits:** conventional (`feat:`, `fix:`, `chore:`, `docs:`), trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Deploy requires push first:** push to origin/master before any prod Ansible run (the server pulls during deploy).

## Confirmed Inputs (from the user)

Repos to provision under `/root/dev` (all public on GitHub; PAT is for rate-limit-free clone + push):

| dir (`/root/dev/<dir>`) | repo | branch | git-crypt |
|---|---|---|---|
| `leaguesphere` | `https://github.com/dachrisch/leaguesphere.git` | `master` | no |
| `league.finance` | `https://github.com/dachrisch/league.finance.git` | `master` | no |
| `groceries` | `https://github.com/dachrisch/groceries-order-tracking.git` | `master` | no |
| `energy` | `https://github.com/dachrisch/energy.consumption.git` | `main` | no |
| `servyy-container` | `https://github.com/dachrisch/servyy-container.git` | `master` | **yes** (unlock) |

- **No `agent` checkout** (explicitly excluded).
- **`servy` special:** the `servyy-container` checkout must be git-crypt unlocked, and an SSH key for `servy.lehel.xyz` must be present so deploys can run from inside opencode.

## Security Notes (carry into execution + history doc)

- **GitHub PAT:** user opted **not to rotate** — the current read+write fine-grained PAT is reused as-is (accepted). Store it only in git-crypt-encrypted `secrets.yml`.
- **git-crypt master key in the container:** accepted trade-off — grants full infra-secret decryption to anyone with container access, which is required for infra work inside opencode. Document it.
- **SSH key (container → host), scoped to localhost:** a **dedicated** ed25519 key (not the user's personal key), authorized on the `cda` user but **restricted to local docker networks** via `from="172.16.0.0/12,127.0.0.1"` in `authorized_keys`. The container reaches the host over the internal docker bridge (`host.docker.internal` → host-gateway, no public hairpin), so the key is unusable from the internet even if leaked.

---

## Task 1: Generate provisioning credentials

Produces the three secret values + one public key that Task 2 pastes into `secrets.yml`. Nothing here is committed.

**Files:**
- Create (scratchpad only, NOT in repo): `<scratchpad>/id_servy`, `<scratchpad>/id_servy.pub`, `<scratchpad>/gitcrypt.key`
- Reference: PAT already stored at `<scratchpad>/gh_pat`

**Interfaces:**
- Produces: four strings consumed by Task 2 — `SERVY_SSH_KEY_B64` (base64, one line), `SERVY_SSH_PUBKEY` (`ssh-ed25519 …`), `GIT_CRYPT_KEY_B64` (base64, one line), `GITHUB_PAT` (from scratchpad).

- [ ] **Step 1: Generate a dedicated ed25519 SSH keypair**

```bash
SCRATCH="$(pwd)/scratch_provision"; mkdir -p "$SCRATCH"; chmod 700 "$SCRATCH"
ssh-keygen -t ed25519 -N "" -C "opencode@servy.lehel.xyz" -f "$SCRATCH/id_servy"
```
Expected: creates `id_servy` and `id_servy.pub`.

- [ ] **Step 2: Verify the key and capture base64 + pubkey**

```bash
ssh-keygen -l -f "$SCRATCH/id_servy"            # prints "256 SHA256:... opencode@servy.lehel.xyz (ED25519)"
base64 -w0 "$SCRATCH/id_servy" > "$SCRATCH/id_servy.b64"
echo "pubkey: $(cat "$SCRATCH/id_servy.pub")"
```
Expected: fingerprint line printed; `id_servy.b64` is a single line.

- [ ] **Step 3: Export the git-crypt key from this repo (run where git-crypt is unlocked)**

```bash
git-crypt export-key "$SCRATCH/gitcrypt.key"
test -s "$SCRATCH/gitcrypt.key" && echo "exported $(wc -c < "$SCRATCH/gitcrypt.key") bytes"
base64 -w0 "$SCRATCH/gitcrypt.key" > "$SCRATCH/gitcrypt.key.b64"
```
Expected: non-empty key file (git-crypt symmetric keys are ~140 bytes); `.b64` single line.

- [ ] **Step 4: Confirm PAT still valid (non-destructive)**

```bash
curl -s -o /dev/null -w "http=%{http_code}\n" \
  -H "Authorization: Bearer $(cat <scratchpad>/gh_pat)" \
  https://api.github.com/repos/dachrisch/leaguesphere
```
Expected: `http=200`.

- [ ] **Step 5: (no commit)** — these are secrets; they are consumed by Task 2 into the encrypted `secrets.yml`. Do not `git add` the scratchpad.

---

## Task 2: Add secrets + repo list to `secrets.yml` and render them into `opencode.env`

**Files:**
- Modify: `ansible/plays/vars/secrets.yml` (the existing `opencode:` block, ~line 117)
- Modify: `ansible/plays/roles/docker_service/templates/opencode/.env.j2`
- Modify (test): `ansible/plays/roles/docker_service/molecule/default/converge.yml`
- Modify (test): `ansible/plays/roles/docker_service/molecule/default/verify.yml`

**Interfaces:**
- Produces env vars in the container (via `env_file: opencode.env`): `GITHUB_PAT`, `GIT_CRYPT_KEY_B64`, `SERVY_SSH_KEY_B64`, `DEV_REPOS_B64`. `DEV_REPOS_B64` is base64 of the JSON array of `{dir, repo, branch, crypt}`. Consumed by `provision-dev.sh` (Task 3).
- Produces var `opencode.servy_ssh_pubkey` consumed by Task 5.

- [ ] **Step 1: Extend the `opencode:` block in `secrets.yml`**

Replace the existing block:
```yaml
opencode:
  server_password: "<existing>"
  circleci_token: "<existing>"
```
with (paste the real values from Task 1 — this file is git-crypt encrypted):
```yaml
opencode:
  server_password: "<existing>"
  circleci_token: "<existing>"
  github_pat: "<PAT from scratchpad/gh_pat>"
  git_crypt_key_b64: "<contents of scratchpad/gitcrypt.key.b64>"
  servy_ssh_key_b64: "<contents of scratchpad/id_servy.b64>"
  servy_ssh_pubkey: "<contents of scratchpad/id_servy.pub>"
  dev_repos:
    - { dir: "leaguesphere",     repo: "https://github.com/dachrisch/leaguesphere.git",            branch: "master", crypt: false }
    - { dir: "league.finance",   repo: "https://github.com/dachrisch/league.finance.git",          branch: "master", crypt: false }
    - { dir: "groceries",        repo: "https://github.com/dachrisch/groceries-order-tracking.git", branch: "master", crypt: false }
    - { dir: "energy",           repo: "https://github.com/dachrisch/energy.consumption.git",       branch: "main",   crypt: false }
    - { dir: "servyy-container", repo: "https://github.com/dachrisch/servyy-container.git",         branch: "master", crypt: true }
```

- [ ] **Step 2: Confirm `secrets.yml` is still encrypted on commit**

```bash
git-crypt status ansible/plays/vars/secrets.yml
```
Expected: `encrypted: ansible/plays/vars/secrets.yml`.

- [ ] **Step 3: Add the new vars to `opencode/.env.j2`**

File `ansible/plays/roles/docker_service/templates/opencode/.env.j2` becomes:
```jinja
OPENCODE_SERVER_PASSWORD={{ opencode.server_password }}
CIRCLECI_TOKEN={{ opencode.circleci_token }}
GITHUB_PAT={{ opencode.github_pat }}
GIT_CRYPT_KEY_B64={{ opencode.git_crypt_key_b64 }}
SERVY_SSH_KEY_B64={{ opencode.servy_ssh_key_b64 }}
DEV_REPOS_B64={{ opencode.dev_repos | to_json | b64encode }}
```

- [ ] **Step 4: Write the failing molecule assertions for the new env vars**

In `converge.yml`, add an opencode render (env only, no docker) after the existing services. Add to the `vars:` block:
```yaml
    opencode:
      server_password: test-opencode-pass
      circleci_token: test-circleci-token
      github_pat: test-github-pat
      git_crypt_key_b64: dGVzdC1jcnlwdC1rZXk=
      servy_ssh_key_b64: dGVzdC1zc2gta2V5
      servy_ssh_pubkey: "ssh-ed25519 AAAATESTKEY opencode@servy.lehel.xyz"
      dev_repos:
        - { dir: "leaguesphere", repo: "https://example.com/x.git", branch: "master", crypt: false }
        - { dir: "servyy-container", repo: "https://example.com/y.git", branch: "master", crypt: true }
```
In `pre_tasks` add `opencode` to the created service dirs loop. In `tasks` add:
```yaml
    - name: Deploy opencode service (env only)
      ansible.builtin.include_role:
        name: docker_service
        tasks_from: main.yml
      vars:
        service_dir: opencode
        manual: true
        env_templates:
          - src: docker.env.j2
            dest: .env
          - src: opencode/.env.j2
            dest: opencode.env
```
In `verify.yml` add:
```yaml
    - name: Check opencode.env exists
      ansible.builtin.stat:
        path: /home/molecule/opencode/opencode.env
      register: oc_env
      failed_when: not oc_env.stat.exists

    - name: Verify opencode.env carries GITHUB_PAT
      ansible.builtin.command:
        cmd: grep -q '^GITHUB_PAT=test-github-pat$' /home/molecule/opencode/opencode.env
      changed_when: false

    - name: Verify opencode.env carries DEV_REPOS_B64 (decodes to JSON with servyy-container)
      ansible.builtin.shell:
        cmd: |
          set -o pipefail
          grep '^DEV_REPOS_B64=' /home/molecule/opencode/opencode.env | cut -d= -f2- | base64 -d | grep -q '"dir": "servyy-container"'
      changed_when: false

    - name: Verify opencode.env has mode 0600
      ansible.builtin.stat:
        path: /home/molecule/opencode/opencode.env
      register: oc_env_perms
      failed_when: oc_env_perms.stat.mode != '0600'
```

- [ ] **Step 5: Run the molecule scenario to verify it passes**

```bash
cd ansible/plays/roles/docker_service
molecule test -s default
```
Expected: converge + verify pass, including the three new opencode assertions; `failed=0`.

- [ ] **Step 6: Commit**

```bash
git add ansible/plays/vars/secrets.yml \
        ansible/plays/roles/docker_service/templates/opencode/.env.j2 \
        ansible/plays/roles/docker_service/molecule/default/converge.yml \
        ansible/plays/roles/docker_service/molecule/default/verify.yml
git commit -m "feat(opencode): add dev-repo list + provisioning secrets to opencode env"
```

---

## Task 3: Create `provision-dev.sh` (idempotent checkout + credential provisioning)

**Files:**
- Create: `opencode/scripts/provision-dev.sh`
- Test (local): run against a temp `HOME` using the real public repos (no PAT needed for read).

**Interfaces:**
- Consumes (env): `GITHUB_PAT`, `GIT_CRYPT_KEY_B64`, `SERVY_SSH_KEY_B64`, `DEV_REPOS_B64`; optional `DEV_DIR` (default `/root/dev`), `HOME` (default `/root`).
- Produces: `$HOME/.ssh/id_servy` (0600) + `$HOME/.ssh/config`, `$HOME/.git-credentials` (0600), cloned/pulled repos under `$DEV_DIR`, git-crypt-unlocked `servyy-container`.

- [ ] **Step 1: Write `opencode/scripts/provision-dev.sh`**

```sh
#!/bin/sh
# Idempotent provisioning of /root/dev checkouts + credentials for OpenCode.
# Runs on every container boot from startup.sh. Safe to re-run.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="${DEV_DIR:-$HOME/dev}"
SSH_DIR="$HOME/.ssh"

log() { echo "[provision-dev] $*"; }

# 1. SSH key + config for servy.lehel.xyz
if [ -n "${SERVY_SSH_KEY_B64:-}" ]; then
  mkdir -p "$SSH_DIR"; chmod 700 "$SSH_DIR"
  echo "$SERVY_SSH_KEY_B64" | base64 -d > "$SSH_DIR/id_servy"
  chmod 600 "$SSH_DIR/id_servy"
  cat > "$SSH_DIR/config" <<EOF
Host servy.lehel.xyz lehel.xyz
  HostName host.docker.internal
  User cda
  IdentityFile ~/.ssh/id_servy
  StrictHostKeyChecking accept-new
EOF
  chmod 600 "$SSH_DIR/config"
  log "ssh key + config written"
fi

# 2. GitHub HTTPS credentials (read+write via PAT)
if [ -n "${GITHUB_PAT:-}" ]; then
  git config --global credential.helper store
  printf 'https://x-access-token:%s@github.com\n' "$GITHUB_PAT" > "$HOME/.git-credentials"
  chmod 600 "$HOME/.git-credentials"
  log "github credential helper configured"
fi
git config --global --add safe.directory '*'
git config --global user.name  "${GIT_AUTHOR_NAME:-opencode}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-opencode@servy.lehel.xyz}"

# 3. Decode git-crypt key (used for repos flagged crypt=true)
CRYPT_KEY=""
if [ -n "${GIT_CRYPT_KEY_B64:-}" ]; then
  CRYPT_KEY="$(mktemp)"
  echo "$GIT_CRYPT_KEY_B64" | base64 -d > "$CRYPT_KEY"
fi

# 4. Clone/pull each declared repo
mkdir -p "$DEV_DIR"
if [ -n "${DEV_REPOS_B64:-}" ]; then
  echo "$DEV_REPOS_B64" | base64 -d | python3 -c '
import json,sys
for r in json.load(sys.stdin):
    print("\t".join([r["dir"], r["repo"], r.get("branch","master"), "1" if r.get("crypt") else "0"]))
' | while IFS="$(printf '\t')" read -r dir repo branch crypt; do
    dest="$DEV_DIR/$dir"
    if [ -d "$dest/.git" ]; then
      log "updating $dir"
      git -C "$dest" remote set-url origin "$repo"
      git -C "$dest" fetch --quiet origin "$branch" \
        && git -C "$dest" checkout --quiet "$branch" \
        && git -C "$dest" pull --quiet --ff-only origin "$branch" \
        || log "WARN: update failed for $dir (continuing)"
    else
      log "cloning $dir"
      git clone --quiet --branch "$branch" "$repo" "$dest" \
        || { log "ERROR: clone failed for $dir"; continue; }
    fi
    if [ "$crypt" = "1" ] && [ -n "$CRYPT_KEY" ]; then
      if git -C "$dest" config --local --get filter.git-crypt.smudge >/dev/null 2>&1; then
        log "$dir already git-crypt unlocked"
      else
        ( cd "$dest" && git-crypt unlock "$CRYPT_KEY" ) \
          && log "git-crypt unlocked $dir" \
          || log "WARN: git-crypt unlock failed for $dir"
      fi
    fi
  done
fi

[ -n "$CRYPT_KEY" ] && rm -f "$CRYPT_KEY"
log "done"
```

- [ ] **Step 2: Lint the script**

```bash
shellcheck opencode/scripts/provision-dev.sh
```
Expected: no errors. (If `shellcheck` is unavailable: `sh -n opencode/scripts/provision-dev.sh` must report no syntax errors.)

- [ ] **Step 3: Local functional test against the real public repos (read-only path)**

```bash
TMP="$(mktemp -d)"
DEV_REPOS='[{"dir":"energy","repo":"https://github.com/dachrisch/energy.consumption.git","branch":"main","crypt":false}]'
env -i HOME="$TMP" PATH="$PATH" \
    DEV_DIR="$TMP/dev" \
    DEV_REPOS_B64="$(printf '%s' "$DEV_REPOS" | base64 -w0)" \
    sh opencode/scripts/provision-dev.sh
test -d "$TMP/dev/energy/.git" && echo "PASS: energy cloned"
# Idempotency: second run should update, not fail
env -i HOME="$TMP" PATH="$PATH" DEV_DIR="$TMP/dev" \
    DEV_REPOS_B64="$(printf '%s' "$DEV_REPOS" | base64 -w0)" \
    sh opencode/scripts/provision-dev.sh && echo "PASS: idempotent re-run"
rm -rf "$TMP"
```
Expected: `PASS: energy cloned` and `PASS: idempotent re-run`.

- [ ] **Step 4: Commit**

```bash
git add opencode/scripts/provision-dev.sh
git commit -m "feat(opencode): add idempotent provision-dev.sh for dev checkouts + creds"
```

---

## Task 4: Wire `provision-dev.sh` into `startup.sh`

**Files:**
- Modify: `opencode/scripts/startup.sh`

**Interfaces:**
- Consumes: `provision-dev.sh` (Task 3) at `/scripts/provision-dev.sh` (already bind-mounted via `./scripts:/scripts:ro`).

- [ ] **Step 1: Insert the provisioning call before the app launch**

In `opencode/scripts/startup.sh`, immediately **before** the final `exec opencode web ...` line, add:
```sh
# 4. Provision dev checkouts & credentials (idempotent, runs every boot)
if [ -f /scripts/provision-dev.sh ]; then
    echo "🌱 [Startup] Provisioning dev checkouts..."
    sh /scripts/provision-dev.sh || echo "⚠️ [Startup] provision-dev.sh reported issues (continuing)"
fi

echo "🚀 [Startup] Setup complete. Launching application..."
```
(Remove the now-duplicate existing "Setup complete. Launching application..." echo so it appears once, right before `exec`.)

- [ ] **Step 2: Syntax-check**

```bash
sh -n opencode/scripts/startup.sh && echo "OK"
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add opencode/scripts/startup.sh
git commit -m "feat(opencode): run provision-dev.sh on container boot"
```

---

## Task 5: Enable container→host SSH, scoped to local docker networks

**Files:**
- Modify: `opencode/docker-compose.yml` (add `extra_hosts` host-gateway mapping; file is git-crypt encrypted)
- Modify: `ansible/plays/roles/user/tasks/docker_extras.yml` (add after the "Create OpenCode data directory" task)

**Interfaces:**
- Consumes: `opencode.servy_ssh_pubkey` (Task 2); the ssh config `HostName host.docker.internal` (Task 3).

- [ ] **Step 1: Map host.docker.internal in the opencode compose**

In `opencode/docker-compose.yml`, under the `opencode` service, add:
```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```
Confirm the file is still encrypted:
```bash
git-crypt status opencode/docker-compose.yml
```
Expected: `encrypted: opencode/docker-compose.yml`.

- [ ] **Step 2: Add the scoped authorized_key task**

In `docker_extras.yml`, after the `Create OpenCode data directory` task, add:
```yaml
- name: Authorize OpenCode container SSH key (scoped to local docker networks)
  ansible.posix.authorized_key:
    user: "{{ create_user }}"
    key: "{{ opencode.servy_ssh_pubkey }}"
    key_options: 'from="172.16.0.0/12,127.0.0.1"'
    comment: "opencode-container-servy"
    state: present
  tags:
    - user.docker.opencode
    - user.ssh.opencode
```

- [ ] **Step 3: Syntax-check the playbook**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add opencode/docker-compose.yml ansible/plays/roles/user/tasks/docker_extras.yml
git commit -m "feat(opencode): scope container SSH key to local docker networks via host-gateway"
```

---

## Task 6: End-to-end validation on servyy-test (fresh volume)

**Files:** none (deployment + verification only).

**Interfaces:** consumes everything from Tasks 2–5.

> Note: servyy-test cannot reach the *prod* host for the SSH-to-lehel test; here we validate key/config files, repo clones, and git-crypt unlock. The live SSH connectivity check happens in Task 7 (prod). `secrets.yml` must be readable (git-crypt unlocked on the deploy machine) so the test render uses the real values.

- [ ] **Step 1: Push the branch and (re)initialize the test container**

```bash
git push origin HEAD
cd scripts && ./setup_test_container.sh
```

- [ ] **Step 2: Force a clean opencode volume on servyy-test, then deploy**

```bash
ssh servyy-test.lxd "cd ~/servyy-container/opencode 2>/dev/null && docker compose down -v || true; docker volume rm opencode_opencode_root 2>/dev/null || true"
cd ansible && ./servyy-test.sh --tags "user.docker.opencode,user.docker.env" --limit servyy-test.lxd
```
Expected: PLAY RECAP `failed=0 unreachable=0`.

- [ ] **Step 3: Confirm the env file rendered with the new vars**

```bash
ssh servyy-test.lxd "grep -c '^DEV_REPOS_B64=' ~/servyy-container/opencode/opencode.env"
```
Expected: `1`.

- [ ] **Step 4: Wait for startup provisioning, then verify checkouts exist**

```bash
ssh servyy-test.lxd "docker logs opencode.web 2>&1 | tr -d '\0' | grep -E 'provision-dev|cloning|unlocked' | tail -20"
ssh servyy-test.lxd "docker exec opencode.web sh -c 'ls -1 /root/dev'"
```
Expected: log shows clones; `ls` lists `leaguesphere league.finance groceries energy servyy-container`.

- [ ] **Step 5: Verify git-crypt unlocked the infra checkout**

```bash
ssh servyy-test.lxd "docker exec opencode.web sh -c 'cd /root/dev/servyy-container && git config --local --get filter.git-crypt.smudge && head -c 40 ansible/plays/vars/secrets.yml'"
```
Expected: prints a `git-crypt smudge` filter line, and `secrets.yml` begins with readable YAML (`create_user:` etc.), NOT the `GITCRYPT` binary magic.

- [ ] **Step 6: Verify SSH key + config present (connectivity tested in prod)**

```bash
ssh servyy-test.lxd "docker exec opencode.web sh -c 'ls -l /root/.ssh/id_servy /root/.ssh/config && ssh-keygen -l -f /root/.ssh/id_servy'"
```
Expected: `id_servy` is `0600`, fingerprint matches Task 1.

- [ ] **Step 7: Verify idempotency across restart**

```bash
ssh servyy-test.lxd "docker restart opencode.web"
# wait for healthy
ssh servyy-test.lxd "for i in $(seq 1 12); do s=\$(docker inspect -f '{{.State.Health.Status}}' opencode.web); [ \"\$s\" = healthy ] && break; sleep 8; done; docker logs opencode.web 2>&1 | grep -E 'already git-crypt unlocked|updating' | tail"
```
Expected: second boot logs "already git-crypt unlocked" / "updating" (no re-clone errors), checkouts still present.

---

## Task 7: Production deploy + verification + history doc

**Files:**
- Create: `history/2026-06-27_opencode-dev-checkout-provisioning.md`

- [ ] **Step 1: (PAT) — no rotation**

Per the user's decision, the existing read+write PAT (already in `secrets.yml` from Task 2) is reused as-is. No action; proceed to Step 2.

- [ ] **Step 2: Merge to master and push**

```bash
git checkout master && git merge --no-ff <branch> && git push origin master
```

- [ ] **Step 3: ASK THE USER for explicit production approval.** Show: the 5 repos, that the opencode volume will self-seed on next boot, and the SSH-key authorization on `cda`. Wait for "yes".

- [ ] **Step 4: Deploy to production (after approval)**

```bash
cd ansible && ./servyy.sh --tags "user.docker.opencode,user.docker.env,user.ssh.opencode" --limit lehel.xyz
```
Expected: PLAY RECAP `failed=0 unreachable=0`.

- [ ] **Step 5: Restart opencode to trigger provisioning, then verify**

```bash
ssh lehel.xyz "docker restart opencode.web"
ssh lehel.xyz "docker exec opencode.web sh -c 'ls -1 /root/dev'"
ssh lehel.xyz "docker exec opencode.web sh -c 'cd /root/dev/servyy-container && head -c 20 ansible/plays/vars/secrets.yml'"
```
Expected: all 5 dirs; `secrets.yml` readable (unlocked).

- [ ] **Step 6: Verify live SSH from container to host (localhost-scoped)**

```bash
ssh lehel.xyz "docker exec opencode.web ssh -o BatchMode=yes servy.lehel.xyz 'echo SSH_OK; hostname'"
```
Expected: `SSH_OK` + the host's hostname (connection goes container → `host.docker.internal` over the docker bridge; source IP is in `172.16.0.0/12`, which the `from=` restriction permits).
> Negative check: confirm `authorized_keys` shows the `from="172.16.0.0/12,127.0.0.1"` prefix on the `opencode-container-servy` entry — `ssh lehel.xyz "grep opencode-container-servy ~/.ssh/authorized_keys"`.

- [ ] **Step 7: Confirm opencode UI works on a real model**

In the UI, open a `leaguesphere` session, select `google/gemini-2.5-flash`, send "hello" → expect a reply (not "Interrupted"). The checkout is now present so file/tool operations resolve.

- [ ] **Step 8: Write the history doc**

Create `history/2026-06-27_opencode-dev-checkout-provisioning.md` documenting: problem (restore lost `/root/dev` + creds), solution (env-driven `provision-dev.sh` on boot), files changed, the security trade-offs (git-crypt key in container, PAT scope/rotation, SSH key), verification commands, and the SSH-hairpin resolution if any.

- [ ] **Step 9: Commit**

```bash
git add history/2026-06-27_opencode-dev-checkout-provisioning.md
git commit -m "docs(opencode): record dev-checkout provisioning rollout"
git push origin master
```

---

## Self-Review

**Spec coverage:**
- Clone `leaguesphere`, `league.finance`, `groceries`, `energy` via PAT/HTTPS → Tasks 2 (repo list), 3 (clone loop), 6/7 (verify). ✓
- `servy` = `servyy-container` clone + **git-crypt unlock** → Task 3 (crypt branch) + Task 6 Step 5 / Task 7 Step 5. ✓
- **SSH key for servy.lehel.xyz, localhost-scoped** → Task 1 (gen), 2 (store), 3 (write key + `host.docker.internal` config), 5 (compose host-gateway + `from=`-restricted authorize), 7 Step 6 (live test + negative check). ✓
- **No `agent`** → excluded from the repo list. ✓
- **Automate (self-heal on rebuild)** → `provision-dev.sh` invoked every boot (Task 4); idempotency proven Task 6 Step 7. ✓
- **Fix now** → deploying the automation + restarting opencode reseeds the running container (Task 7 Step 5); for an immediate seed before full rollout, the same `provision-dev.sh` can be run via `docker exec` (see Execution Handoff). ✓

**Placeholder scan:** No "TBD"/"handle errors"/"similar to". Real secret values intentionally referenced as scratchpad placeholders per the no-plaintext-secrets constraint — actual values are entered into the git-crypt-encrypted `secrets.yml` at execution, never into this doc. ✓

**Type consistency:** Env var names identical across Task 2 (`.env.j2`), Task 3 (consumed), Task 4 (wiring): `GITHUB_PAT`, `GIT_CRYPT_KEY_B64`, `SERVY_SSH_KEY_B64`, `DEV_REPOS_B64`. `dev_repos` item schema `{dir, repo, branch, crypt}` consistent in `secrets.yml`, molecule, and `provision-dev.sh` parser. `opencode.servy_ssh_pubkey` defined Task 2, consumed Task 5. ✓
