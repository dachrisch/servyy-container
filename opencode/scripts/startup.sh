#!/bin/sh
set -e

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
# apt-get update
# apt-get install -y git curl python3 python3-pip
apk update
# openssh-client-default, NOT the `openssh` meta installed here since d0d95b7:
# the meta pulls openssh-server, i.e. the sshd that showed up in this container
# without anyone starting it. The base image ships no OpenSSH at all (its
# /etc/apk/world is alpine-baselayout, alpine-keys, apk-tools, busybox, ...), so
# this line alone is what put sshd on the filesystem. The client stays: `ssh`
# for git/github, `ssh-keyscan` for known_hosts, `ssh-keygen` for commit signing.
apk add git curl github-cli nodejs npm python3 py3-pip openssh-client-default git-crypt gettext

# 1a. Purge any sshd this container already carries.
# Containers created before the line above was fixed (2026-11-05) installed the
# full openssh meta, i.e. openssh-server, on every boot. It never bound :22, but
# it is Alpine/musl without PAM — precisely the recipe behind the Nov 2026
# "sshole" bug: on musl, crypt() returns "*" when it cannot hash (passwords
# > 256 bytes), so an account locked with a bare `*` in shadow accepts any
# password of 257-1024 bytes. Fixed upstream in openssh 10.6p2; Alpine's master
# got it 2026-11-05, but the v3.24 repo this image tracks still ships
# 10.3_p1-r2. Nothing here needs sshd, and anything running as root in the
# container (agents included) could start it.
# `apk del openssh` (not openssh-server) is the effective command — removing
# only the server package is refused while the meta depends on it. Guarded so a
# failure can't kill the boot (set -e).
if apk info -e openssh-server >/dev/null 2>&1; then
    echo "🔒 [Startup] Removing openssh-server (this container runs no sshd)..."
    if apk del openssh >/dev/null 2>&1; then
        echo "📍 [Startup] openssh-server removed"
    elif apk del openssh-server >/dev/null 2>&1; then
        echo "📍 [Startup] openssh-server removed (direct)"
    else
        echo "⚠️ [Startup] openssh-server removal failed (ssh client unaffected)"
    fi
fi

# 1b. Headless browser for the chrome-devtools MCP (record-tutorial & co.).
# The ghcr.io/anomalyco/opencode:latest image does not ship chromium, but
# chrome-devtools-mcp needs a Chrome/Chromium to launch. Alpine's `chromium`
# apk provides /usr/lib/chromium/chromium, which the MCP is pointed at via
# --executablePath (see scripts/opencode.json.template). Idempotent, and
# guarded so a transient apk failure can't kill the whole boot: the MCP would
# be unavailable, but every other session still works.
if [ ! -x /usr/lib/chromium/chromium ]; then
    echo "🌐 [Startup] Installing chromium for the chrome-devtools MCP..."
    apk add --no-cache chromium \
        && echo "📍 [Startup] chromium installed" \
        || echo "⚠️ [Startup] chromium install failed (chrome-devtools MCP unavailable)"
else
    echo "📍 [Startup] chromium already present"
fi

# 1c. Python deps for LeagueSphere's record-tutorial yt_upload.py (server-side
# YouTube upload). google-* live in the image rootfs (not the persistent
# volume), so this re-installs on recreate; the import guard makes it a no-op
# within a boot and keeps the whole boot alive if PyPI is unreachable.
if ! python3 -c 'import googleapiclient.discovery, google_auth_oauthlib.flow, google_auth_httplib2' 2>/dev/null; then
    echo "🐍 [Startup] Installing YouTube upload Python deps..."
    python3 -m pip install --no-cache-dir --break-system-packages \
        google-api-python-client google-auth-oauthlib google-auth-httplib2 \
        && echo "📍 [Startup] YouTube upload deps installed" \
        || echo "⚠️ [Startup] YouTube upload deps install failed (yt_upload.py unavailable)"
else
    echo "📍 [Startup] YouTube upload deps already present"
fi

# 2. GitHub SSH Setup
echo "🔑 [Startup] Updating GitHub SSH host key (GitHub rotates keys periodically)..."
ssh-keygen -R github.com 2>/dev/null || true
ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null || true

# 3. GitHub CLI Wrapper Setup
echo "🔐 [Startup] Setting up GitHub CLI PAT wrapper..."
if [ -f "/usr/bin/gh" ]; then
    if [ -f "/usr/bin/gh.real" ]; then
        echo "📍 [Startup] gh binary already renamed to gh.real"
    else
        echo "📍 [Startup] Renaming real gh binary to gh.real..."
        mv /usr/bin/gh /usr/bin/gh.real || echo "⚠️ [Startup] Failed to rename gh binary"
    fi
fi
if [ ! -x "/opencode/bin/gh" ]; then
    echo "⚠️ [Startup] GitHub CLI wrapper not found at /opencode/bin/gh - wrapper will not function"
fi

# 3b. gh-stack extension (required by the gh-stack skill).
# Installed once into /root/.local/share/gh (persists via opencode_root
# volume); the guard makes this a no-op on later boots. Auth strategy:
# the gh wrapper hard-fails when no PAT is configured, so use it only
# when GITHUB_PAT_DACHRISCH is present; otherwise fall back to gh.real,
# which can install this PUBLIC extension unauthenticated (rate limits
# apply). Never fail the boot here.
echo "🧩 [Startup] Ensuring gh-stack extension..."
gh_ext_bin="/usr/bin/gh.real"
if [ -n "${GITHUB_PAT_DACHRISCH:-}" ] && [ -x "/opencode/bin/gh" ]; then
    export GH_TOKEN="$GITHUB_PAT_DACHRISCH"
    gh_ext_bin="gh"
fi
if "$gh_ext_bin" extension list 2>/dev/null | grep -q 'gh-stack'; then
    echo "📍 [Startup] gh-stack extension already installed"
else
    "$gh_ext_bin" extension install github/gh-stack \
        && echo "📍 [Startup] gh-stack extension installed" \
        || echo "⚠️ [Startup] gh-stack extension install failed (continuing)"
fi
unset GH_TOKEN || true
# Non-interactive prerequisites from the gh-stack skill:
git config --global rerere.enabled true || true
git config --global remote.pushDefault origin || true

# 3c. graphify CLI (required by the graphify skill).
# The skill's own bootstrap cannot supply it here: ./skills is bind-mounted
# read-only (`:ro` in docker-compose.yml), so `graphify install` cannot write
# the skill into it, and the image ships no uv for `uv tool install` to use.
# So the package must already be importable when a session starts it.
# Installed at boot rather than baked in: the image is upstream
# (ghcr.io/anomalyco/opencode), so there is no Dockerfile of ours to pin it in.
# Wheel-only install, no compiler needed: every dependency of graphifyy ships a
# musllinux_1_2_x86_64 wheel (networkx, numpy, rapidfuzz, pyyaml, tree-sitter
# and its ~25 language packs). Lives in the image rootfs, so it re-installs on
# container recreate (~40s); the import guard makes it a no-op within a boot,
# and a failure here must never take the boot down with it.
if ! python3 -c 'import graphify' 2>/dev/null; then
    echo "🕸️ [Startup] Installing graphify CLI..."
    python3 -m pip install --no-cache-dir --break-system-packages graphifyy \
        && echo "📍 [Startup] graphify installed" \
        || echo "⚠️ [Startup] graphify install failed (graphify skill unavailable)"
else
    echo "📍 [Startup] graphify CLI already present"
fi

# The CLI floats (pip installs latest on every recreate) while the skill is a
# pinned copy shipped from setup-home's agent-config/skills/graphify (its
# .graphify_version says which CLI it was generated for). Log the mismatch so a
# lagging skill is visible in `docker logs` instead of silently missing flags.
if command -v graphify >/dev/null 2>&1; then
    skill_ver=$(cat /root/.config/opencode/skills/graphify/.graphify_version 2>/dev/null || true)
    cli_ver=$(graphify --version 2>/dev/null | awk '{print $NF}' || true)
    if [ -n "$skill_ver" ] && [ -n "$cli_ver" ] && [ "$skill_ver" != "$cli_ver" ]; then
        echo "⚠️ [Startup] graphify CLI ${cli_ver} != shipped skill ${skill_ver}"
        echo "⚠️ [Startup] Refresh agent-config/skills/graphify in setup-home if the skill lags the CLI"
    fi
fi

# graphify writes graphify-out/ into every tree it scans. /root/dev holds shared
# checkouts that claude-hub also uses, so keep graphs out of `git status` there
# via git's own default global excludes file (no core.excludesFile needed).
gitignore_global="/root/.config/git/ignore"
mkdir -p "$(dirname "$gitignore_global")"
grep -qxF 'graphify-out/' "$gitignore_global" 2>/dev/null \
    || echo 'graphify-out/' >> "$gitignore_global"

# 4. Configuration Substitution
echo "⚙️ [Startup] Configuring OpenCode..."
CONFIG_DIR="/root/.config/opencode"
mkdir -p "$CONFIG_DIR"

if [ -f "/scripts/opencode.json.template" ]; then
    # Set default if not provided
    export CIRCLECI_BASE_URL="${CIRCLECI_BASE_URL:-https://circleci.com}"

    # We only substitute specific variables to avoid breaking $schema
    echo "⚙️ [Startup] Generating opencode.json from template..."
    envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY $OPENCODE_GO_API_KEY' < /scripts/opencode.json.template > "$CONFIG_DIR/opencode.json"
fi

# Global AGENTS.md: the zero-dependency, V2-native cross-session memory channel.
# Loaded into every session and combined with each repo's own AGENTS.md.
if [ -f "/scripts/AGENTS.md" ]; then
    echo "🧠 [Startup] Deploying global AGENTS.md..."
    cp /scripts/AGENTS.md "$CONFIG_DIR/AGENTS.md"
fi

# Cleanup legacy files from removed plugins and superseded configs (one-way,
# idempotent). The V1 tui.json is superseded by the V2 cli.json; this
# deployment is headless, so a stale file left in the volume must not linger.
rm -f "$CONFIG_DIR/opencode-mem.jsonc"
rm -f "$CONFIG_DIR/tui.json"

# 4b. Configure git to prefer SSH over HTTPS for github.com
git config --global --add safe.directory '*'
git config --global user.name  "${GIT_AUTHOR_NAME:-opencode}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-opencode@servy.lehel.xyz}"
git config --global url."git@github.com:".insteadOf "https://github.com/"

# 5. Extensions (Placeholder)
# echo "🧩 [Startup] Installing extensions..."
# code-server --install-extension <extension-id>

# 6. Provision dev checkouts & credentials (idempotent, runs every boot)
if [ -f /scripts/provision-dev.sh ]; then
    echo "🌱 [Startup] Provisioning dev checkouts..."
    sh /scripts/provision-dev.sh || echo "⚠️ [Startup] provision-dev.sh reported issues (continuing)"
fi

echo "🚀 [Startup] Setup complete. Launching application..."
# V2 has no `web` subcommand (it would be parsed as a directory); `serve` is the
# foreground V2 API + web server. Basic auth still comes from
# OPENCODE_SERVER_PASSWORD.
exec opencode serve --hostname 0.0.0.0 --port 4096
