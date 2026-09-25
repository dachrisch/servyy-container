#!/bin/sh
# Long-tail disk-growth backstop for claude-hub (infra-specific, not part of upstream june-hub).
#
# session-reaper.mjs's own model only ever deletes a worktree via a task session's own
# close-request + the user's explicit OK -- nothing auto-deletes. That is the right default, but
# it removes the old prune-sessions.sh's automatic disk-reclaim: a forgotten/abandoned task
# session now just sits parked forever. This script is a deliberate, narrow, infra-specific
# exception: force-close (never hand-roll deletion -- always go through session-reaper.mjs's own
# --action close) any job session that has been parked for a very long time
# (CLAUDE_HUB_FORCE_CLEANUP_DAYS, default 75 days). Run weekly from a host-side systemd timer
# (claude-hub-force-cleanup.timer), well below the frequency of the reaper's own 15-minute park
# sweep -- see history/2026-09-26_claude-hub-worktree-dispatch-rework.md for why this exists and
# why it's safe.
#
# session-reaper.mjs's own --action close still refuses a dirty worktree outright (exits non-zero
# with close-blocked/dirty_worktree) and it always keeps every branch -- a force-close here can
# never lose committed work, only tear down a stale, already-clean workspace directory.
# Unpushed-but-clean commits are not a block (only a warning): the branch keeps them regardless,
# recoverable later via the `reopen` command close-planned prints.
set -eu

VENDOR_ROOT="${CLAUDE_HUB_VENDOR_ROOT:-/opt/vendor}"
REAPER="$VENDOR_ROOT/skills/session-reaper/scripts/session-reaper.mjs"
DAYS="${CLAUDE_HUB_FORCE_CLEANUP_DAYS:-75}"

log() { echo "[force-cleanup-stale] $*"; }

log "checking for job sessions parked more than $DAYS day(s)..."

fleet_json="$(node "$REAPER" --action list --all)"

# Only ever background 'job' sessions (agent-deck 'deck' sessions have no .spinup.json and
# --action close would refuse them anyway), currently parked, whose parked_at is older than the
# threshold.
stale_ids="$(printf '%s' "$fleet_json" | DAYS="$DAYS" node -e '
const fs = require("fs");
const days = Number(process.env.DAYS);
const cutoffMs = days * 24 * 60 * 60 * 1000;
const data = JSON.parse(fs.readFileSync(0, "utf8"));
const now = Date.now();
for (const s of data.sessions || []) {
  if (s.kind !== "job" || s.now !== "parked" || !s.parked_at) continue;
  const parkedAt = Date.parse(s.parked_at);
  if (Number.isNaN(parkedAt)) continue;
  if (now - parkedAt >= cutoffMs) console.log(s.id);
}
')"

if [ -z "$stale_ids" ]; then
  log "nothing parked long enough to force-close"
  exit 0
fi

printf '%s\n' "$stale_ids" | while IFS= read -r id; do
  [ -n "$id" ] || continue

  # Dry run first, every time: this is what actually enforces "never force past a dirty
  # worktree" -- a dirty repo makes session-reaper.mjs exit non-zero with
  # close-blocked/dirty_worktree before anything is touched, and we simply skip that id.
  if ! dry_out="$(node "$REAPER" --action close --id "$id" --dry-run 2>&1)"; then
    log "skip $id: dry-run refused it: $dry_out"
    continue
  fi

  log "closing $id (parked past the ${DAYS}-day threshold, dry-run reports it's safe)..."
  if close_out="$(node "$REAPER" --action close --id "$id" 2>&1)"; then
    log "closed $id: $close_out"
  else
    log "ERROR: close failed for $id: $close_out"
  fi
done

log "done"
