#!/bin/sh
# Prune old claude-hub dispatch sessions: worktrees (and their tmux sessions
# and local branches) created by launch-session.sh whose .claude-hub-created
# marker is older than CLAUDE_HUB_PRUNE_DAYS (default 14). Never touches the
# shared $HOME/dev/<owner>/<repo> clone itself, and never pushes or deletes
# anything remote -- only local worktrees/branches/tmux sessions this same
# service created.
#
# No arguments. Meant to run on a schedule (systemd timer -> `docker exec
# claude-hub.hub sh /scripts/prune-sessions.sh`), but safe to run by hand.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="$HOME/dev"
WORKTREES_DIR="$HOME/worktrees"

# Empty or non-numeric -> the documented default of 14.
CLAUDE_HUB_PRUNE_DAYS="${CLAUDE_HUB_PRUNE_DAYS:-14}"
case "$CLAUDE_HUB_PRUNE_DAYS" in
  ''|*[!0-9]*) CLAUDE_HUB_PRUNE_DAYS=14 ;;
esac

log() { echo "[prune-sessions] $*" >&2; }

# KEEP IN SYNC with sanitize_session_name() in launch-session.sh -- both must
# turn the same "<owner>-<repo>-<branch>" string into the same tmux session
# name, or this script's kill-session targets the wrong (or no) session.
sanitize_session_name() {
  printf '%s\n' "$1" | sed 's/[^A-Za-z0-9_-]/-/g'
}

if [ ! -d "$WORKTREES_DIR" ]; then
  log "no $WORKTREES_DIR, nothing to prune"
  exit 0
fi

# JUDGMENT CALL (brief flags this as "your call, document which you
# picked"): age worktrees by the marker FILE'S MTIME via `find -mtime`,
# rather than parsing the ISO-8601 timestamp written inside it. Reasons:
#   - the marker's content is never touched after creation, so its mtime and
#     its content agree in the only case that matters (no drift to reconcile);
#   - `find -mtime` needs no date arithmetic/parsing in a shell that has no
#     GNU date (-d) to lean on -- busybox `date` cannot reliably parse
#     arbitrary ISO-8601 strings back into epoch seconds, so the
#     content-parsing alternative would need a node one-liner for what `find`
#     already does natively;
#   - `-mtime +N` (older than N*24h, i.e. N days) is the same "days old"
#     semantics the brief describes.
# The marker's content stays human-readable UTC for anyone inspecting the
# worktree by hand; it is not read by this script.
tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

# $HOME/worktrees/<owner>-<repo>/<branch>/.claude-hub-created is 3 levels
# below $HOME/worktrees (depth 0), so mindepth == maxdepth == 3.
find "$WORKTREES_DIR" -mindepth 3 -maxdepth 3 -type f -name '.claude-hub-created' \
  -mtime "+$CLAUDE_HUB_PRUNE_DAYS" > "$tmpfile" 2>/dev/null || true

if [ ! -s "$tmpfile" ]; then
  log "nothing older than ${CLAUDE_HUB_PRUNE_DAYS}d"
  exit 0
fi

pruned=0
# Read from a file, not `find | while`: a pipe's right-hand side runs in a
# subshell in POSIX sh, which would silently drop updates to $pruned once the
# loop ends. Redirecting from $tmpfile keeps the loop (and $pruned) in this
# shell.
while IFS= read -r marker; do
  [ -n "$marker" ] || continue
  worktree_dir="$(dirname "$marker")"
  branch_name="$(basename "$worktree_dir")"

  # The leaf "$WORKTREES_DIR/<owner>-<repo>" directory name cannot be split
  # back into <owner>/<repo> unambiguously -- either half can itself contain
  # '-' (e.g. "servyy-container"). Ask git instead: every clone under
  # $DEV_DIR/*/* that owns this worktree lists it verbatim in its own
  # `git worktree list`, which sidesteps the ambiguity entirely.
  dev_dest=""
  for repo_dir in "$DEV_DIR"/*/*; do
    [ -d "$repo_dir/.git" ] || continue
    if git -C "$repo_dir" worktree list --porcelain 2>/dev/null \
        | grep -qxF "worktree $worktree_dir"; then
      dev_dest="$repo_dir"
      break
    fi
  done

  if [ -z "$dev_dest" ]; then
    log "WARN: no owning clone under $DEV_DIR found for $worktree_dir, skipping (left in place for manual review)"
    continue
  fi

  owner="$(basename "$(dirname "$dev_dest")")"
  repo="$(basename "$dev_dest")"
  session_name="$(sanitize_session_name "${owner}-${repo}-${branch_name}")"

  # Liveness check: the .claude-hub-created marker is stamped once at
  # creation and never refreshed, so age-since-creation alone cannot tell an
  # abandoned worktree from one that's still being actively worked on. If the
  # tmux session is still alive, that overrides the age check entirely --
  # skip pruning (and do NOT kill the session or remove the worktree) rather
  # than destroying uncommitted work with no warning.
  if tmux has-session -t "$session_name" 2>/dev/null; then
    log "skipping $owner/$repo branch=$branch_name worktree=$worktree_dir: session=$session_name is still active"
    continue
  fi

  tmux kill-session -t "$session_name" 2>/dev/null || true

  if git -C "$dev_dest" worktree remove --force "$worktree_dir" 2>/dev/null; then
    git -C "$dev_dest" branch -D "$branch_name" 2>/dev/null || true
    log "pruned $owner/$repo branch=$branch_name worktree=$worktree_dir session=$session_name"
    pruned=$((pruned + 1))
  else
    log "WARN: git worktree remove failed for $worktree_dir (left in place; branch not deleted)"
  fi
done < "$tmpfile"

log "done (pruned $pruned)"
