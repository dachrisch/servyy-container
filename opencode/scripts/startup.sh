#!/bin/sh
set -e

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
# apt-get update
# apt-get install -y git curl python3 python3-pip
apk update
apk add git curl github-cli nodejs npm python3 py3-pip openssh git-crypt gettext

# 2. GitHub CLI Wrapper Setup
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

# 3. Configuration Substitution
echo "⚙️ [Startup] Configuring OpenCode..."
CONFIG_DIR="/root/.config/opencode"
mkdir -p "$CONFIG_DIR"

if [ -f "/scripts/opencode.json.template" ]; then
    # Set default if not provided
    export CIRCLECI_BASE_URL="${CIRCLECI_BASE_URL:-https://circleci.com}"
    
    # We only substitute specific variables to avoid breaking $schema
    echo "⚙️ [Startup] Generating opencode.json from template..."
    envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL $DASHSCOPE_API_KEY' < /scripts/opencode.json.template > "$CONFIG_DIR/opencode.json"
fi

# 4. Extensions (Placeholder)
# echo "🧩 [Startup] Installing extensions..."
# code-server --install-extension <extension-id>

# 5. Provision dev checkouts & credentials (idempotent, runs every boot)
if [ -f /scripts/provision-dev.sh ]; then
    echo "🌱 [Startup] Provisioning dev checkouts..."
    sh /scripts/provision-dev.sh || echo "⚠️ [Startup] provision-dev.sh reported issues (continuing)"
fi

echo "🚀 [Startup] Setup complete. Launching application..."
# Execute the original command passed to the container, or default
exec opencode web --hostname 0.0.0.0 --port 4096
