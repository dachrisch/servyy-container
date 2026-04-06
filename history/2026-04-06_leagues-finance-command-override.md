# 2026-04-06 Override leagues-finance App Command

## Problem

The pre-built image `dachrisch/league.finance:latest` has an incorrect default command or entrypoint that does not point to the correct server entrypoint (`dist/src/server/index.js`), causing the container to fail on startup.

## Fix

Added a `command` override in `leagues-finance/docker-compose.yml` for the `app` service to explicitly run the server using Node.js:
```yaml
command: ["node", "dist/src/server/index.js"]
```

## Files Changed

- `leagues-finance/docker-compose.yml`

## Verification

- `yamllint leagues-finance/docker-compose.yml` passed.
- The command matches the requirements provided in the task.
