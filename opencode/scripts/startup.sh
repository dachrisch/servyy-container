#!/bin/sh
set -e

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
# apt-get update
# apt-get install -y git curl python3 python3-pip
apk update
apk add git curl github-cli nodejs npm python3 py3-pip openssh git-crypt gettext

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

if [ -f "/scripts/tui.json" ]; then
    echo "⚙️ [Startup] Deploying tui.json..."
    cp /scripts/tui.json "$CONFIG_DIR/tui.json"
fi

# Cleanup legacy files from removed plugins (one-way, idempotent).
rm -f "$CONFIG_DIR/opencode-mem.jsonc"

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
# Execute the original command passed to the container, or default
exec opencode web --hostname 0.0.0.0 --port 4096
