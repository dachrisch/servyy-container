# OpenCode Persistence & Declarative Setup Plan

**Goal:** Solve the issue of losing extensions and system packages on container restart by implementing a declarative startup script, while also ensuring SSH keys are persisted.

**Approach:** Lifecycle Hooks (Option 2) + Ephemeral Storage (Strict Declarative).
**Security:** SSH keys persisted via bind mount.

---

## Architecture

We will inject a startup script into the container that runs on every boot. This script will install system packages and extensions before launching the main application. This ensures the environment is always consistent with the declarative script.

### Directory Structure Changes

```text
opencode/
├── docker-compose.yml      # Modified to mount script & SSH
├── data/                   # Existing config persistence
├── ssh/                    # NEW: Persisted SSH keys
└── scripts/                # NEW: Directory for lifecycle scripts
    └── startup.sh          # The setup logic
```

## Implementation Steps

### Task 1: Create Startup Script

**File:** `opencode/scripts/startup.sh`

A bash script that:
1.  Updates apt repositories.
2.  Installs defined system packages (e.g., `git`, `curl`, `python3`).
3.  Installs defined extensions (syntax depends on OpenCode CLI, generic example below).
4.  Executes the original container command.

```bash
#!/bin/bash
set -euo pipefail

echo "🔧 [Startup] Initializing development environment..."

# 1. System Packages
echo "📦 [Startup] Installing system packages..."
apt-get update
apt-get install -y git curl

# 2. Extensions (Placeholder - replace with actual OpenCode CLI if available)
# echo "🧩 [Startup] Installing extensions..."
# code-server --install-extension ...

echo "🚀 [Startup] Setup complete. Launching application..."
exec web --hostname 0.0.0.0 --port 4096
```

### Task 2: Configure Docker Compose

**File:** `opencode/docker-compose.yml`

Modifications:
1.  **Volumes:**
    *   Map `./scripts:/scripts:ro`
    *   Map `./ssh:/root/.ssh` (Persist SSH identity)
2.  **Command:**
    *   Override to run the script: `command: ["/bin/bash", "/scripts/startup.sh"]`

```yaml
services:
  opencode:
    # ... existing config ...
    command: ["/bin/bash", "/scripts/startup.sh"]
    volumes:
      - ./data:/root/.config/opencode
      - ./db:/root/.local/share/opencode
      - ./scripts:/scripts:ro       # <--- NEW
      - ./ssh:/root/.ssh            # <--- NEW
```

### Task 3: Infrastructure Setup

**Actions:**
1.  Create `opencode/ssh` directory on host.
2.  Create `opencode/scripts` directory on host.
3.  Set strict permissions on `opencode/ssh` (chmod 700) to prevent SSH warnings.

## Usage Guide

*   **To add a package:** Edit `opencode/scripts/startup.sh` and restart the container (`docker compose restart opencode`).
*   **SSH Keys:** Put your keys in `opencode/ssh/`. They will appear in `~/.ssh` inside the container.
