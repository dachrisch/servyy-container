#!/bin/sh
set -e

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
# apt-get update
# apt-get install -y git curl python3 python3-pip
apk update
apk add git curl github-cli nodejs npm python3 py3-pip openssh git-crypt gettext

# 2. Configuration Substitution
echo "⚙️ [Startup] Configuring OpenCode..."
if [ -f "/root/.config/opencode/opencode.json" ]; then
    # Set default if not provided
    export CIRCLECI_BASE_URL="${CIRCLECI_BASE_URL:-https://circleci.com}"
    
    # We only substitute specific variables to avoid breaking $schema
    # We create a temporary file to avoid reading and writing to the same file simultaneously
    envsubst '$CIRCLECI_TOKEN $CIRCLECI_BASE_URL' < /root/.config/opencode/opencode.json > /tmp/opencode.json
    cat /tmp/opencode.json > /root/.config/opencode/opencode.json
    rm /tmp/opencode.json
fi

# 3. Extensions (Placeholder)
# echo "🧩 [Startup] Installing extensions..."
# code-server --install-extension <extension-id>

echo "🚀 [Startup] Setup complete. Launching application..."
# Execute the original command passed to the container, or default
exec opencode web --hostname 0.0.0.0 --port 4096
