# 2026-03-19 Gameday Designer Migration Fix

## Context
The CI job "Check Django Migrations" was failing with `InconsistentMigrationHistory`:
> Migration gameday_designer.0001_initial is applied before its dependency gamedays.0023_gameinfo_league_group on database 'default'.

This occurred because `gamedays.0023` was "faked" on staging recently to resolve a deployment issue (column `league_group` already existed), resulting in a newer applied timestamp than `gameday_designer.0001`.

## Changes
- **Source Code (`leaguesphere` repo):**
    - `gameday_designer/migrations/0001_initial.py`: Relaxed dependency from `gamedays.0023_gameinfo_league_group` to `gamedays.0022_person`.
    - This allows `gameday_designer` to be validly applied *before* `0023` (matching historical reality on staging) without breaking dependency checks.
    - Verified that `gameday_designer` does not use the `league_group` field added in `0023`.

## Verification
- CI "Check Django Migrations" should now pass as the dependency tree is consistent with the applied state on staging.
