#!/bin/sh
set -e

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
# apt-get update
# apt-get install -y git curl python3 python3-pip
apk update
apk add git curl github-cli nodejs npm python3 py3-pip

# 2. Extensions (Placeholder)
# echo "🧩 [Startup] Installing extensions..."
# code-server --install-extension <extension-id>

echo "🚀 [Startup] Setup complete. Launching application..."
# Execute the original command passed to the container, or default
exec opencode web --hostname 0.0.0.0 --port 4096
