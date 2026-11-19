# OpenCode Derived Image Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the upstream `ghcr.io/anomalyco/opencode:2.3.0` with a thin
multi-arch derived image that has every static dependency pre-installed, so a
container recreate goes straight to `opencode serve` instead of spending ~20s
installing packages.

**Architecture:** One `Dockerfile` in `opencode/` doing `FROM` the pinned
upstream tag, installing the apk packages, Python deps and gh-stack once at
build time. A GitHub Actions workflow builds `linux/amd64` + `linux/arm64` with
buildx and pushes `dachrisch/opencode` to Docker Hub (the dachrisch org's
registry convention). `startup.sh` keeps its install blocks but they become
no-ops (every block is already guarded), so the same script still works against
the upstream image — that is the rollback path.

**Tech Stack:** Alpine 3.24 (base image is Alpine/musl, Python 3.14.10), apk,
pip, Docker buildx + QEMU, GitHub Actions.

---

## Baseline (measured 2026-11-17, after Part 1)

| Host | Steady-state boot (to `listening on`) |
|---|---|
| codey (x86_64) | 22 s |
| codacle (aarch64) | 26 s |

Remaining cost is almost entirely section 1 of `startup.sh`: `apk update` +
installing git/curl/github-cli/nodejs/npm/python3/py3-pip/openssh-client/git-crypt/gettext/bash
(~17 s), chromium (~7 s), YouTube Python deps (~7 s).

Target after Part 2: **< 8 s**.

## Constraints discovered

- Base image is **Alpine 3.24**, not Debian. Use `apk`, not `apt-get`.
- **`chromium` IS available on aarch64** (`156.0.8078.79-r0`). A first test
  appeared to show otherwise — that was a missing apk index, not a missing
  package. Verified with `apk update` first.
- Baking chromium pulls ~196 apk packages. Expect a **materially larger image**
  (~+300–400 MB uncompressed). Accepted: it is pulled once per update, not per
  boot, and watchtower handles the update.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Registry | Docker Hub `dachrisch/opencode` | dachrisch org convention (see `devhub`); `DOCKER_TOKEN` is an org secret |
| Tags | `latest`, `<upstream-version>` (`2.3.0`), `2.3.0-r<N>` | `r<N>` lets us rebuild our layer without bumping upstream |
| Chromium | baked in | removes 7 s/boot + a network dependency; size cost accepted |
| Rollback | revert compose `image:` to upstream tag | `startup.sh` stays idempotent and upstream-compatible |

---

### Task 1: Add the Dockerfile

**Files:**
- Create: `opencode/Dockerfile`

**Step 1: Write the Dockerfile**

```dockerfile
# Derived from the pinned upstream image purely to pre-install static
# dependencies. Everything here used to run in scripts/startup.sh on every
# container recreate (~20s of apk + pip). None of it depends on runtime data.
#
# The base is Alpine 3.24, so apk — not apt-get. Keep the FROM tag in sync with
# what docker-compose.yml used before this image existed; renovate should bump
# it (datasource: docker, package: ghcr.io/anomalyco/opencode).
FROM ghcr.io/anomalyco/opencode:2.3.0

# Section 1 of startup.sh, verbatim. openssh-client-default, NOT the `openssh`
# meta: the meta pulls openssh-server, i.e. an sshd nothing needs (session
# history: history/2026-11-13_opencode-container-bash.md and the Nov 2026
# "sshole" audit). Baking the client only means the startup purge becomes moot,
# but it is left in place as a safety net for older images.
RUN apk add --no-cache \
        git \
        curl \
        github-cli \
        nodejs \
        npm \
        python3 \
        py3-pip \
        openssh-client-default \
        git-crypt \
        gettext \
        bash

# Headless browser for the chrome-devtools MCP. The base image does not ship
# one, and scripts/opencode.json.template points the MCP at
# /usr/lib/chromium/chromium via --executablePath. Available on amd64 and arm64.
RUN apk add --no-cache chromium

# Python deps for LeagueSphere's record-tutorial yt_upload.py.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
        google-api-python-client \
        google-auth-oauthlib \
        google-auth-httplib2

# gh-stack extension (used by the gh-stack skill). Needs a token for API calls,
# so install from the public repo without auth.
RUN gh extension install github/gh-stack || \
    echo "WARN: gh-stack install failed at build time (skill unavailable)"

# Smoke test at build time: fail the build rather than the boot.
RUN bash -c 'true' \
 && python3 -c 'import googleapiclient.discovery' \
 && test -x /usr/lib/chromium/chromium \
 && echo "build-time smoke test OK"

# Deliberately no ENTRYPOINT/CMD override: inherit upstream and let
# scripts/startup.sh run exactly as before.
```

**Step 2: Commit**

```bash
git add opencode/Dockerfile
git commit -m "feat(opencode): add derived image pre-installing static deps"
```

---

### Task 2: Add a .dockerignore

**Files:**
- Create: `opencode/.dockerignore`

**Step 1: Write it**

```
# Nothing from the service directory belongs in the build context — the
# Dockerfile only installs packages on top of the upstream image.
*
```

**Step 2: Commit**

```bash
git add opencode/.dockerignore
git commit -m "chore(opencode): keep the derived-image build context empty"
```

---

### Task 3: Build and verify locally (both architectures)

**Files:** none (verification only)

**Step 1: Build amd64**

```bash
cd opencode
docker buildx build --platform linux/amd64 -t opencode-derived:test-amd64 --load .
```

Expected: build succeeds, smoke test prints `build-time smoke test OK`.

**Step 2: Verify the contents**

```bash
docker run --rm --entrypoint sh opencode-derived:test-amd64 -c \
  'bash -c true \
   && /usr/lib/chromium/chromium --version \
   && gh extension list | grep -q gh-stack && echo "gh-stack OK" \
   && command -v git-crypt gettext envsubst node npm | wc -l'
```

Expected: a chromium version line, `gh-stack OK`, `6`.

**Step 3: Build and verify arm64**

```bash
docker buildx build --platform linux/arm64 -t opencode-derived:test-arm64 --load .
docker run --rm --entrypoint sh --platform linux/arm64 opencode-derived:test-arm64 -c \
  'python3 -c "import googleapiclient.discovery; print(\"youtube OK\")" \
   && /usr/lib/chromium/chromium --version'
```

Expected: `youtube OK`, chromium version.

**Step 4: Record image sizes**

```bash
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep opencode-derived
```

Record both sizes in the commit message — they set expectations for pull time.

---

### Task 4: Trial the image on codacle before wiring CI

**Files:** none (verification only)

**Step 1: Retag and load onto codacle**

`docker-compose.yml` hardcodes the image (no variable to override), so the trial
retags our build **over the upstream tag locally** — nothing is edited on disk,
and `docker pull` restores upstream afterwards.

```bash
docker save opencode-derived:test-arm64 | ssh -i ~/.ssh/id_rsa -o IdentitiesOnly=yes \
  cda@138.2.180.191 'docker load && \
    docker tag opencode-derived:test-arm64 ghcr.io/anomalyco/opencode:2.3.0 && \
    docker images ghcr.io/anomalyco/opencode --format "{{.Tag}} {{.Size}}"'
```

**Step 2: Recreate and measure**

```bash
ssh -i ~/.ssh/id_rsa -o IdentitiesOnly=yes cda@138.2.180.191 \
  'cd /home/cda/servyy-container/opencode && \
   docker compose up -d --force-recreate opencode'
```

**Step 3: Measure time to `listening on`**

```bash
ssh -i ~/.ssh/id_rsa -o IdentitiesOnly=yes cda@138.2.180.191 \
  'S=$(date +%s); cd /home/cda/servyy-container/opencode; \
   docker compose up -d --force-recreate opencode >/dev/null 2>&1; \
   for i in $(seq 1 120); do docker logs opencode.web 2>&1 | grep -q "listening on" && break; sleep 1; done; \
   echo "$(( $(date +%s) - S ))s"'
```

Expected: **< 10 s** (baseline was 26 s).

**Step 4: Verify the site**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://codacle.lehel.xyz/
```

Expected: `200`.

---

### Task 5: Add the build/publish workflow

**Files:**
- Create: `.github/workflows/opencode-image.yml`

**Step 1: Write the workflow**

```yaml
name: opencode image

# Builds the derived opencode image. Separate from ci.yml (ansible tests) so a
# Dockerfile change never triggers a Molecule run and vice versa.
on:
  workflow_dispatch:
    inputs:
      upstream_version:
        description: "Upstream tag the Dockerfile FROMs, e.g. 2.3.0"
        required: true
        default: "2.3.0"
      revision:
        description: "Our layer revision (bump to rebuild without upstream)"
        required: true
        default: "1"
  push:
    branches: [master]
    paths:
      - "opencode/Dockerfile"
      - ".github/workflows/opencode-image.yml"

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_TOKEN }}

      - name: Build and push (amd64 + arm64)
        uses: docker/build-push-action@v6
        with:
          context: opencode
          file: opencode/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            dachrisch/opencode:latest
            dachrisch/opencode:${{ inputs.upstream_version || '2.3.0' }}-r${{ inputs.revision || '1' }}
```

**Step 2: Verify the workflow parses**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/opencode-image.yml')); print('yaml OK')"
```

**Step 3: Commit and run it manually**

```bash
git add .github/workflows/opencode-image.yml
git commit -m "ci(opencode): build and publish the multi-arch derived image"
git push origin master
gh workflow run opencode-image.yml --repo dachrisch/servyy-container \
  -f upstream_version=2.3.0 -f revision=1
gh run watch --repo dachrisch/servyy-container
```

Expected: green run; `dachrisch/opencode:2.3.0-r1` visible on Docker Hub.

---

### Task 6: Switch the compose file to the derived image

**Files:**
- Modify: `opencode/docker-compose.yml:17`

**Step 1: Change the image line**

```yaml
    image: dachrisch/opencode:2.3.0-r1
```

Keep the surrounding comment explaining *why* we no longer float upstream —
update it to say the derived tag is pinned and bumped deliberately.

**Step 2: Commit**

```bash
git add opencode/docker-compose.yml
git commit -m "feat(opencode): run the derived image instead of upstream"
```

---

### Task 7: Trim the now-redundant startup work

**Files:**
- Modify: `opencode/scripts/startup.sh:20-60` (apk + chromium + YouTube blocks)

**Step 1: Make the apk step a no-op when everything is already present**

Replace the unconditional `apk update` + `apk add` with a guard, so the derived
image skips the network round-trip entirely while the upstream image (rollback
path) still self-heals:

```sh
if ! command -v bash >/dev/null 2>&1 || ! command -v git-crypt >/dev/null 2>&1; then
    echo "📦 [Startup] Installing system packages..."
    apk update
    apk add git curl github-cli nodejs npm python3 py3-pip \
            openssh-client-default git-crypt gettext bash
else
    echo "📍 [Startup] system packages already present"
fi
```

**Step 2: Leave the chromium and YouTube guards untouched**

They are already `if [ ! -x ... ]` / import-guarded, so they no-op on the
derived image and still work on upstream. No change needed — do not "clean them
up", they are the rollback safety net.

**Step 3: Commit**

```bash
git add opencode/scripts/startup.sh
git commit -m "perf(opencode): skip the apk step when packages are baked in"
```

---

### Task 8: Roll out to both hosts and measure

**Files:** none

**Step 1: Deploy to codacle, then codey**

```bash
cd ansible
ansible-playbook plays/user.yml -i production --limit oracle-codey.lehel.xyz \
  --tags user.docker
ansible-playbook plays/user.yml -i production --limit codey.lehel.xyz \
  --tags user.docker
```

**Step 2: Measure each host twice** (first recreate pulls the new image)

Use the Task 4 Step 3 measurement command against each host.

Expected: **< 10 s** steady state on both, down from 22 s / 26 s.

**Step 3: Verify behaviour, not just speed**

```bash
# both serve
curl -sS -o /dev/null -w 'codey %{http_code}\n'   https://code.lehel.xyz/
curl -sS -o /dev/null -w 'codacle %{http_code}\n' https://codacle.lehel.xyz/

# the MCP still has its browser
ssh codey.lehel.xyz 'docker exec opencode.web /usr/lib/chromium/chromium --version'
```

**Step 4: Confirm state survived** (volumes must not have moved)

```bash
ssh -i ~/.ssh/id_rsa -o IdentitiesOnly=yes cda@138.2.180.191 \
  'sudo ls -lh /var/lib/docker/volumes/opencode_opencode_root/_data/.local/share/opencode/opencode.db'
```

Expected: still 84 MB, same md5 as codey at cutover time.

---

### Task 9: Update strategy for the upstream base

**Files:** none — verified, no config change needed.

**Step 1:** `renovate.json` extends `config:recommended`, which already enables
the **dockerfile** manager, so it will pick up
`FROM ghcr.io/anomalyco/opencode:x.y.z` with no rule added. Confirmed
2026-11-17.

**Step 2:** The same config enables the **docker-compose** manager for
`**/docker-compose*.{yml,yaml}`, so renovate will also try to bump
`image: dachrisch/opencode:2.3.0-r1` from Docker Hub. That is *our own* image,
so it becomes a self-referential update. Either accept it (a useful nudge that
a rebuild is available) or add a narrow `packageRules` ignore for
`matchPackageNames: ["dachrisch/opencode"]`. Decide when the first PR appears —
do not pre-emptively silence it.

**Step 3:** Bumping `FROM` does **not** update the tag in `docker-compose.yml`
(a derived image is not a 1:1 mapping), so note in the Dockerfile comment that
the two move together.

**Step 4:** Confirm renovate opens a PR after the next upstream release:

```bash
gh pr list --repo dachrisch/servyy-container --author app/renovate
```

---

### Task 10: History entry and rollback note

**Files:**
- Create: `history/2026-11-17_opencode-derived-image.md`

**Step 1:** Write the ADR (per the infrastructure-history-tracking skill) with:
measured before/after boot times on both architectures, image sizes for
amd64/arm64, and the rollback procedure:

```bash
# rollback = revert one line, containers self-heal on boot
git revert <commit touching opencode/docker-compose.yml>
cd ansible && ansible-playbook plays/user.yml -i production \
  --limit codey.lehel.xyz,oracle-codey.lehel.xyz --tags user.docker
```

**Step 2: Commit**

```bash
git add history/2026-11-17_opencode-derived-image.md
git commit -m "docs(opencode): record the derived image decision and timings"
```

---

## Risks

| Risk | Mitigation |
|---|---|
| arm64 build fails (QEMU + chromium compile time) | Build is CI-only, allowed to take 10+ min; no local dev loop depends on it |
| Derived image drifts from upstream behaviour | Dockerfile only *adds* packages; no ENTRYPOINT/CMD/ENV overrides |
| Bigger image slows watchtower updates | Pull happens per update only; ~400 MB on a 100 Mbit line is ~30 s, once |
| We miss an upstream security fix | Pinned `FROM`, renovate bump, and the `r<N>` tag makes rebuilding cheap |
| gh-stack install needs a token at build time | Falls back to a warning; startup still installs it if the build skipped it |

## Out of scope

- Baking the dev checkouts (they are user data and live on a volume).
- Changing `OPENCODE_SERVER_PASSWORD` / auth.
- The cutover itself (`code.lehel.xyz` DNS) — separate work.
