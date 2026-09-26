---
name: repo-task-dispatch
description: Use when the user asks to start, resume, or continue work on a specific repo or task -- e.g. "start work on the leagues-finance bug", "spin up a session for servyy-container to fix the DNS thing", "continue the job-search scraper work", "new session for X", "launch a task for Y", "start a session that touches both X and Y". Discovers the right gh-dash-tagged repo(s) (across the dachrisch and bumbleflies orgs), sets up an isolated git worktree per repo, and starts a new independent Remote-Control-visible Claude Code background session for the task.
---

# Repo Task Dispatch

This skill runs inside the claude-hub `hub` session itself (the persistent,
Remote-Control-visible Claude Code process anchored at `$HOME/dev/$INFRA_REPO`
that Ansible boots on codey.lehel.xyz). It is how the hub turns a chat
request into a brand-new, independent, Remote-Control-visible Claude Code
background session for one task, with an isolated git-worktree workspace for
every repo the task touches.

## When to Use This Skill

The user, talking to the hub session (via claude.ai/code or any Remote
Control client), asks it to start, resume, or continue work on some repo or
task -- e.g. "start work on the leagues-finance bug", "spin up a session for
servyy-container to fix the DNS thing", "continue the job-search scraper
work". Anything that implies "go do this somewhere else, as its own session"
belongs here, as opposed to work the hub does itself in its own anchor repo.

## How It Works

The actual dispatch logic lives in `claude-hub/scripts/spinup-repo.sh`
(mounted read-only at `/scripts/spinup-repo.sh`), which resolves the repo(s)
via the same `gh-dash`-topic discovery as before and then hands off to the
vendored `spinup-session.mjs` (see `claude-hub/vendor/VENDORED.md`), which
owns everything deterministic: the workspace directory, the git worktrees,
the branch, the session name, and starting the background Remote Control
session. This skill's job is to invoke `spinup-repo.sh` correctly, write a
good brief, and relay its result -- it does not reimplement any of the
repo-resolution, cloning, worktree, or session-starting logic itself.

### 1. Settle the repo(s), description, and brief

- **Repo(s)**: one task can touch more than one repo -- give `spinup-repo.sh`
  every directory name the task genuinely needs (a comma or space-separated
  list), not just the first one that comes to mind. If the user gave an
  exact `owner/repo` for each, skip straight to step 2. Otherwise, pass
  whatever search term(s) the user gave (a repo name, a topic, a fragment --
  substring matching against `nameWithOwner` across the `dachrisch` and
  `bumbleflies` orgs' `gh-dash`-tagged repos) and let the script resolve them.
- **Description**: 2 to 5 words, short and descriptive -- it becomes part of
  the session name and the branch slug.
- **Brief**: what the new session is told, written to a file and passed via
  `--task-file` (avoids shell-quoting problems; multi-line briefs are the
  norm). Include what's wrong or wanted, anything the user just said, where
  to start looking, and the goal stated so the session can check when it's
  done. A session that starts with a vague brief burns its own context
  rediscovering what you already know.

### 2. Run the script

```bash
sh /scripts/spinup-repo.sh "<targets>" "<desc>" ["<ticket>"] ["<task-file>"]
```

`<targets>` is one or more comma/space-separated `owner/repo` values or
search terms (e.g. `"dachrisch/leagues-finance"` or
`"leagues-finance,leagues-schema"`). `<ticket>` and `<task-file>` are
optional -- pass an empty string for `<ticket>` if you have a task file but
no ticket id.

### 3. Read the result and relay it

The script's stdout is one of:

- **A candidate list** (one `owner/repo` per line, non-zero exit): a search
  term matched zero or several `gh-dash`-tagged repos. Show the list to the
  user (or say none matched) and ask them to pick / give a more specific
  term, then re-invoke with the exact `owner/repo` for that target.
- **A single JSON event** from `spinup-session.mjs` (exit 0 or 1):
  - `session-ready`: report the session name (the user opens it in
    claude.ai/code under that name), the workspace path, and the repos +
    branches created.
  - `session-exists`: a session is already running in that exact workspace --
    report its name and message it instead of starting a second one (never
    start a duplicate).
  - `spinup-blocked`: report the `error` and `message` verbatim, per repo --
    these are usually a bad repo name, a branch already in use, or a
    clone/network/auth issue worth showing the user directly.

If the script fails for a reason other than "multiple candidates" or a
`spinup-blocked` event (e.g. it errors before printing any JSON at all --
clone failure, `gh` auth issue), relay the stderr output verbatim rather than
guessing at the cause.

## Manual Debugging Reference

If a launched session needs checking on directly (stuck, want to see its
output, etc.), from a shell on the host or inside the container:

```bash
# List every session on this machine, live and stopped, with what it's doing:
docker exec -it claude-hub.hub node /opt/vendor/skills/session-reaper/scripts/session-reaper.mjs --action list --all --text

# Attach to / tail a specific job's output (job id from the list above):
docker exec -it claude-hub.hub claude attach <job-id>
docker exec claude-hub.hub claude logs <job-id>
```

Prefer the `session-fleet` skill (run from within the hub session itself, via
claude.ai/code) for day-to-day fleet questions -- the raw `docker exec`
commands above are the fallback for when the hub itself is unresponsive.

Parking of idle sessions and closing of finished ones is handled by the
`session-fleet` skill and its systemd timer, not from inside this skill --
see `claude-hub/skills/session-fleet/SKILL.md`. A long-tail disk-growth
backstop (`claude-hub/scripts/force-cleanup-stale.sh`) also runs on its own
weekly timer; nothing here needs to trigger either manually.

## What This Skill Does Not Do

- It does not do the repo's actual work -- that happens in the newly spawned
  session, which is a separate Claude Code instance with its own context.
- It does not merge, push, or clean up branches/worktrees -- that is either
  the spawned session's own job (as part of its task, via its own
  `close-request` when done) or the `session-fleet` skill's (for idle/
  abandoned ones).
- It does not manage GitHub PATs, git-crypt keys, or any credential
  material -- those are provisioned into the container's environment by
  Ansible and consumed transparently by `spinup-repo.sh` and the git
  credential helper it relies on.
