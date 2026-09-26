---
name: session-fleet
description: Use when the user asks what sessions are running, wants the fleet view ("what is running", "which sessions are open", "what is waiting on me", "show me the fleet"), wants a parked session revived, or when a dispatched task session messages the hub with a close-request (asking to be closed once its work is done). Runs inside the claude-hub hub session on codey.lehel.xyz.
---

# Session Fleet

This skill runs inside the claude-hub `hub` session itself. It is how the hub
answers "what's running", revives a parked session, and safely closes a
task session once it says it's done -- always through the vendored
`session-reaper.mjs` (see `claude-hub/vendor/VENDORED.md`), never by hand.

Automatic parking of idle/never-prompted/cleared sessions already runs on
its own schedule (`claude-hub-reaper.timer`, every 15 minutes, host-side,
outside this skill) -- you don't need to trigger that. This skill is for
on-demand fleet questions, reviving something the user wants back, and
handling a `close-request` that arrives while the hub is being talked to.

## What you decide and what the script decides

`skills/session-reaper/scripts/session-reaper.mjs` (mounted at
`/opt/vendor/skills/session-reaper/scripts/session-reaper.mjs`) decides
everything mechanical: which session is what, the ledger, the stop, the
revive, and the close's dirty-worktree check. **Never `claude stop` or
`claude rm` a session by hand on this skill's behalf** -- `rm` deletes the
conversation and the ledger cannot bring that back. What's left to you is
reading its output back to the user in plain words, and asking for the OK a
close needs.

## The fleet view

```bash
node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action list --all --text
```

This answers "what is running", "what was parked recently", and "what is
waiting on me". Drop `--text` for the JSON form (`reaper-fleet` event) if you
need to reason about fields rather than show a table. Each row's `now` is one
of `live`, `parked`, `stopped`, `gone`, or `closed`; `resume` (in the JSON
form) carries the exact command to bring a `parked`/`stopped`/`gone` one
back.

## Revive

```bash
node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action revive --id <id>
```

Brings a parked session back (`claude respawn`, keeping the job id, name, and
Remote Control), re-arms any loops the ledger recorded, and drops it off the
parked list.

## Handling an incoming `close-request`

A dispatched task session's own workspace `CLAUDE.md` (written by
`spinup-session.mjs`) tells it to message the hub `close-request <job id>`
by itself, without being asked, once its brief's definition of done is met
and its worktrees are clean. It may end with a `learnings:` block: one line
each, `- <target> | <feedback|project|reference> | <kebab-name> | <the fact
in one line>`.

When that message arrives:

1. **Dry-run first, always**:
   ```bash
   node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action close --id <job id> --dry-run
   ```
   - `close-blocked` / `dirty_worktree`: uncommitted changes exist -- report
     this to the user and to the session; nothing is closed until it's
     clean.
   - `close-blocked` / `not_closable` or `not_a_spinup_workspace` or
     `not_found`: something is wrong with the id -- report the error
     verbatim, do not guess.
   - `close-planned`: safe to proceed. Show the user the workspace, repos,
     branches, and any `warnings` (unpushed commits are only a warning --
     the branch keeps them regardless).

2. **Ask the user for the OK** (`AskUserQuestion`): *Close it* (recommended
   when there are no warnings) / *Keep it running*. If there are unpushed
   commits, say so and don't default to *Close it*. If nobody is at the hub,
   the request waits -- never close on a timeout.

3. **If there's a `learnings:` block**, ask the user which to keep, then file
   each approved one **before** closing (closing deletes `.spinup.json`,
   which maps target names to memory dirs):
   ```bash
   node /opt/vendor/skills/session-reaper/scripts/file-learning.mjs \
     --workspace <workspace path> --target <target> --type <feedback|project|reference|user> \
     --name <kebab-name> --title '<one line>' --description '<one line>' \
     --body-file <file with the fact, why, and how to apply> \
     [--index index_<area>.md] --commit
   ```
   `--target` is a repo directory from the workspace, or `general` (the
   hub's own repo) -- never write a fact about one customer/repo to
   `general`, since that loads into every session. Pass text through a file
   or single quotes, never double quotes (a task session's text may contain
   backticks or `$(...)`).

4. **Only after the user's OK**, run the real close:
   ```bash
   node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action close --id <job id>
   ```
   `session-closed` lists what was removed and kept, and a `reopen` command
   (spinup with the same branch, reattaching it in a fresh session) --
   branches and commits are always kept, only the workspace directory and
   its `TASK.md`/`CLAUDE.md`/`.spinup.json` are removed.

## Manual debugging

```bash
# From a shell on the host, if the hub itself is unresponsive:
docker exec -it claude-hub.hub node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action list --all --text
docker exec -it claude-hub.hub claude attach <job-id>
docker exec claude-hub.hub claude logs <job-id>
```

## What runs outside this skill

- **Parking** (`--action run`, every 15 minutes): `claude-hub-reaper.timer`
  on the host, `docker exec`-ing into the container. Nothing here needs to
  trigger it.
- **Long-tail force-cleanup** (`claude-hub/scripts/force-cleanup-stale.sh`,
  weekly): force-closes sessions parked far longer than
  `CLAUDE_HUB_FORCE_CLEANUP_DAYS` (default 75 days) -- a deliberate,
  infra-specific exception to "never close on a timeout", reusing this same
  `--action close` (still refuses a dirty worktree, still always keeps
  branches). See `history/2026-09-26_claude-hub-worktree-dispatch-rework.md`.
- **Starting a new task session**: `repo-task-dispatch`
  (`claude-hub/scripts/spinup-repo.sh`), not this skill.
