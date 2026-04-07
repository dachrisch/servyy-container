# Watchtower Consolidation Design

**Date:** 2026-04-07
**Status:** Approved

## Problem

Watchtower instances are scattered across multiple service directories (`groceries`, `energy`, `leaguesphere/staging`), each with their own scope and poll interval. This makes configuration inconsistent and harder to manage. The goal is one central place for watchtower instances with per-project scope labels.

## Design

### Two watchtower instances in `portainer/docker-compose.yml`

| Instance | Scope | Poll Interval | Purpose |
|---|---|---|---|
| `watchtower-prod` | `prod` | 7200s (2h) | Stable third-party images |
| `watchtower-dev` | `dev` | 300s (5min) | Actively developed personal images |

### Scope assignments

| Service | File | Scope |
|---|---|---|
| portainer | `portainer/docker-compose.yml` | `prod` |
| all other existing `prod` services | various | `prod` (unchanged) |
| groceries | `groceries/docker-compose.yml` | `dev` |
| energy | `energy/docker-compose.yml` | `dev` |
| leagues-finance | `leagues-finance/docker-compose.yml` | `dev` |
| leaguesphere staging (www, app) | `leaguesphere/deployed/docker-compose.staging.yaml` | `dev` |

### Files changed

| File | Action |
|---|---|
| `portainer/docker-compose.yml` | Rename `watchtower` → `watchtower-prod`, add `watchtower-dev` |
| `groceries/docker-compose.yml` | Remove `watchtower` service; change scope label to `dev` |
| `energy/docker-compose.yml` | Remove `watchtower` service; change scope label to `dev` |
| `leagues-finance/docker-compose.yml` | Add `com.centurylinklabs.watchtower.scope=dev` to `app` service |
| `leaguesphere/deployed/docker-compose.staging.yaml` | Remove `watchtower` service; change scope labels `ls-staging` → `dev` |

## Rationale

- Portainer already owns docker socket access and the prod watchtower — natural home for both instances.
- Scope labels let each project declare which watchtower monitors it without hosting their own instance.
- Shorter dev interval (300s) enables faster feedback loop during active development.
