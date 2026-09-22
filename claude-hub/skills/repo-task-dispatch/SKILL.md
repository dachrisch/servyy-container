---
name: repo-task-dispatch
description: Dispatch a new per-repo Claude Code session from the claude-hub session
triggers:
  - "start work on"
  - "continue work on"
  - "new session"
  - "spin up"
  - "launch session"
  - "work on the"
  - "task for"
  - repo
delegates_to: []
reads:
  - scripts/launch-session.sh
  - scripts/prune-sessions.sh
---

# Repo Task Dispatch

This skill runs inside the claude-hub `hub` session itself (the persistent,
Remote-Control-visible Claude Code process anchored at `$HOME/dev/$INFRA_REPO`
that Ansible boots on codey.lehel.xyz). It is how the hub turns a chat
request into a brand-new, independent, Remote-Control-visible Claude Code
session for one repo and one task.

## When to Use This Skill

The user, talking to the hub session (via claude.ai/code or any Remote
Control client), asks it to start, resume, or continue work on some repo or
task -- e.g. "start work on the leagues-finance bug", "spin up a session for
servyy-container to fix the DNS thing", "continue the job-search scraper
work". Anything that implies "go do this somewhere else, as its own session"
belongs here, as opposed to work the hub does itself in its own anchor repo.

## How It Works

The actual spawning logic lives in `claude-hub/scripts/launch-session.sh`
(mounted read-only at `/scripts/launch-session.sh` in the container). This
skill's job is to invoke it correctly and relay its output -- it does not
reimplement any of the repo-resolution, cloning, worktree, or tmux logic
itself.

### 1. Resolve the repo

If the user gave an exact `owner/repo` (e.g. `dachrisch/servyy-container`),
skip straight to step 2.

Otherwise, call the script with whatever search term the user gave (a repo
name, a topic, a fragment -- substring matching against `nameWithOwner`
across the `dachrisch` and `bumbleflies` orgs' `gh-dash`-tagged repos):

```bash
sh /scripts/launch-session.sh "<search term>" "<task title>"
```

- **Exit 0**: the script found exactly one match and already launched the
  session -- go to step 3 (relay the summary), you're done.
- **Exit 1 with candidates printed to stdout** (more than one match, one
  `owner/repo` per line): show the list to the user and ask them to pick one.
  Once they do, re-invoke with the exact `owner/repo` (step 2).
- **Exit 1 with no candidates**: tell the user no `gh-dash`-tagged repo
  matched; ask for a more specific term or an exact `owner/repo`.

### 2. Launch with an exact owner/repo

```bash
sh /scripts/launch-session.sh "<owner>/<repo>" "<task title>"
```

Quote `<task title>` as one argument -- it becomes both the branch-name slug
and the string handed to `claude --remote-control` in the new session. A
short, descriptive title works best (it's what shows up as the branch name
and, likely, the session's display name).

This clones/updates `$HOME/dev/<owner>/<repo>` if needed, creates a fresh
worktree + branch under `$HOME/worktrees/<owner>-<repo>/<branch>`, and starts
a new detached tmux session running `claude --remote-control` there.

### 3. Relay the result to the user

On success the script prints a short summary to stdout:

```
repo: <owner>/<repo>
branch: <branch>
worktree: <worktree path>
tmux session: <tmux session name>
```

Pass this along to the user essentially as-is, plus: the new session will
appear in their claude.ai/code session list (Remote Control) shortly, under
whatever display name `--remote-control` gives it -- they don't need to do
anything else to reach it.

If the script exits non-zero for a reason other than "multiple candidates"
(clone failure, worktree failure, tmux failure), relay the error output
(stderr) verbatim rather than guessing at the cause -- these are usually
GitHub/network/auth issues worth showing the user directly.

## Manual Debugging Reference

If a launched session needs checking on directly (stuck, want to see its
output, etc.), from a shell on the host or inside the container:

```bash
# List all sessions currently running inside claude-hub (from the host):
docker exec -it claude-hub.hub tmux list-sessions

# Attach to one of them (Ctrl-b d to detach without killing it):
docker exec -it claude-hub.hub tmux attach -t <session-name>
```

Pruning of old sessions (worktrees/branches/tmux sessions older than
`CLAUDE_HUB_PRUNE_DAYS`, default 14 days) runs on its own systemd timer on
the host, not from inside this skill -- see `claude-hub/scripts/prune-sessions.sh`.
Nothing here needs to trigger it manually.

## What This Skill Does Not Do

- It does not do the repo's actual work -- that happens in the newly spawned
  session, which is a separate Claude Code instance with its own context.
- It does not merge, push, or clean up branches/worktrees -- that is either
  the spawned session's own job (as part of its task) or the pruning timer's
  (for abandoned ones).
- It does not manage GitHub PATs, git-crypt keys, or any credential
  material -- those are provisioned into the container's environment by
  Ansible and consumed transparently by `launch-session.sh` and the git
  credential helper it relies on.
