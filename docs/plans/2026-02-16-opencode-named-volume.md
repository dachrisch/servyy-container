# OpenCode Named Volume Migration Plan

**Goal:** Simplify persistence by replacing multiple host bind-mounts with a single Docker named volume for the `/root` directory.

**Approach:** 
- Keep declarative system package setup via `startup.sh`.
- Move user state (SSH, config, extensions) into a managed named volume.

---

## 1. Directory Structure Cleanup

We will remove the now redundant local directories that were used for bind-mounts.

```text
opencode/
├── docker-compose.yml      # Updated to use named volume
├── scripts/                # KEPT: For declarative setup
│   └── startup.sh          
├── data/                   # REMOVE (now in volume)
├── ssh/                    # REMOVE (now in volume)
└── db/                     # REMOVE (now in volume)
```

## 2. Implementation Tasks

### Task 1: Update Docker Compose

**File:** `opencode/docker-compose.yml`

1.  Define the named volume in the top-level `volumes` section.
2.  Update the `opencode` service to mount the named volume to `/root`.
3.  Remove specific mappings for `./data`, `./db`, and `./ssh`.
4.  Keep the `./scripts` mapping for the startup script.

```yaml
services:
  opencode:
    # ... image, entrypoint, etc ...
    volumes:
      - opencode_root:/root         # <--- Consolidated Volume
      - ./scripts:/scripts:ro       # <--- Kept for GitOps setup
    # ... networks, labels ...

volumes:
  opencode_root:                    # <--- NEW
```

### Task 2: Update Git Configuration

**File:** `opencode/.gitignore`

Remove references to the local directories that are no longer needed.

### Task 3: Infrastructure Verification (servyy-test)

1.  Sync the new `docker-compose.yml` to the test server.
2.  Stop and remove previous containers/volumes: `docker compose down -v`.
3.  Start with the new configuration: `docker compose up -d`.
4.  Verify `/root/.ssh` and `/root/.config` are persistent by restarting the container.

---

## 3. Deployment Safety

Because we are switching from bind-mounts to a named volume, any data currently in `opencode/data` or `opencode/ssh` on the server will **NOT** be automatically moved into the new volume.

**Manual Step Required (One-time):**
If there is critical data in those folders on production, we must copy it into the volume after it's created, or manually seed the volume once.
