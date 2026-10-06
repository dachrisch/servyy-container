# 2026-10-06 claude-hub: worktree corruption, zombie agents, and two reaper mislabels

Follow-up to PR #164 (merged and deployed to test + production this session). The hub
session on codey gave a brief of its last several dispatches; three of its findings were
real bugs in `session-reaper.mjs`, confirmed by reading the code and then reproduced by
hand on servyy-test.lxd before being fixed here. A fourth, related gap (zombie agents) was
found while verifying the first.

## Bug 1: a pruned worktree admin-dir name gets reused by an unrelated later job, and the
old workspace silently starts reading the new job's git state

**Symptom reported by the hub:** two task workspaces (`fix-stale-eslint-code-scanning`,
`rate-hardening-test-issues`) showed `HEAD` on another session's branch and 200+ phantom
"dirty" files; `close` refused both with `dirty_worktree`.

**Cause:** `spinup-session.mjs` creates each repo's worktree at
`<workspace>/<owner>/<repo>` and lets `git worktree add` name the admin directory
(`<source-git-dir>/worktrees/<name>`) itself — which it does from the path's plain
basename, i.e. just the repo name. That name repeats across every task dispatched against
the same repo. If an old workspace's admin-dir entry is ever pruned (e.g. `git worktree
prune`, or anything else that invalidates it) while its on-disk directory is not also
removed, the name is free again. A later, completely unrelated spinup on the same repo
then gets that exact name back. From that point on, the *old* directory's `.git` file
(`gitdir: <source-git-dir>/worktrees/<name>`) resolves into the *new* worktree's index and
HEAD — the old job's files are untouched on disk, but anything run inside that directory
(`git status`, `git rev-parse HEAD`) reports the new job's branch and a huge bogus diff
against it.

`close` trusted that output at face value. Worse, a forced close (ignoring
`dirty_worktree`) would have run `git worktree remove <old-path>` against the *new* job's
admin-dir registration, deleting the wrong worktree.

**Fix:** a new `registeredWorktree(repoSource, path)` helper asks the *source* repo's own
`git worktree list --porcelain` whether `path` is still registered there, and on which
branch — the one place the hijack above cannot hide, since the source repo's registry
always reflects who currently owns an admin-dir name. `close` now runs this check per repo
before trusting `gitFacts`' `dirty_files`/`unpushed`. A mismatch (not registered, or
registered under a different branch than `.spinup.json` recorded) is reported as
`corrupted` with a reason, kept out of the normal `dirty_worktree` refusal, and cleaned up
with a plain `rm -rf` instead of `git worktree remove` — never touching the *other* job's
live registration.

**Known limitation — not fixed here:** this detects and safely recovers from the
collision; it does not make the collision rarer. Doing that means giving every worktree a
globally unique admin-dir name, and `git worktree add` has no flag to set one directly
(it is always derived from the path's basename). Changing the on-disk path layout to make
basenames unique would touch the session briefing text, the `EnterWorktree`-denial
message, and `.spinup.json`'s `path` field, for comparatively low payoff now that the
dangerous outcome (wrong-worktree removal, trusted bogus facts) is closed off. Left as a
follow-up idea, not attempted.

## Bug 2 (found while verifying Bug 1): a workspace that is already gone cannot be closed

`close` required reading `.spinup.json` from `a.cwd` and failed `not_a_spinup_workspace`
if the directory did not exist. Any workspace removed by hand — including, previously,
every case of Bug 1 before this fix existed, since the only way to recover one was to
delete it manually — left its `claude agents` entry permanently stuck `blocked`, with no
way to deregister it short of `claude stop` run by hand outside the reaper's bookkeeping
(no ledger entry, no `session-closed` event). Five such zombies were present in production
at the time of this writing (`1987 fix template officials 500`, `1988 rework 1992
stateless service`, `2029 review share widget PR`, `2042 review pr 2042 scope`, `fix stale
eslint code scanning`).

**Fix:** `close` now checks `existsSync(ws)` first. If the workspace is already gone, it
stops the agent (if running) and records the close in the ledger — no files to remove, but
the agent itself is no longer left dangling.

**Not done here:** actually closing the five pre-existing zombies in production. Doing
that is an operational step (run `close --id <id>` for each, which this fix now makes
possible), not a code change — left for the user/hub to run after this PR deploys.

## Bug 3: a branch pushed without local tracking is reported as "not pushed"

**Symptom reported by the hub:** `5dc0038b` reported "1 local commit not pushed", but the
commit was already on `origin/claude/2029-review-share-widget-pr`.

**Cause:** when `@{upstream}` isn't configured, the old fallback diffed `HEAD` against the
task's *base* branch (e.g. `origin/master`) and reported that count as "not pushed" —
conflating "ahead of base" with "ahead of the remote branch of the same name", which is a
different number whenever the branch has actually been pushed.

**Fix:** the fallback now checks whether `origin/<branch>` exists (after a quiet `git
fetch`) before picking a comparison point. If it exists, it diffs against that instead —
genuinely reflecting push status. The `no_upstream` framing ("stays on the branch") is now
only used when nothing on origin matches either.

## Bug 4 (cleanup, not from the brief): empty `<owner>/` directories pile up under closed workspaces

Every repo lives at `<workspace>/<owner>/<repo>`. `close` only ever checked whether
`<workspace>` itself was empty before removing it; removing `<repo>` never emptied
`<workspace>` because `<owner>/` was always still there, so the final rmdir never fired.
7 empty directories had accumulated in production.

**Fix:** after removing each repo, `close` now walks up from its parent directory,
`rmdir`-ing empty directories up to (not past) the workspace root, before the existing
workspace-root check runs.

## Verification

No automated test harness exists for these vendored scripts (unlike the Ansible roles);
following the pattern of prior claude-hub fixes (PRs #158/#160/#161/#164), this was
verified by hand against the real scripts on servyy-test.lxd, not just `node --check`:

1. Built a real worktree (`spinup-session.mjs --no-start`) for `dachrisch/servyy-container`,
   then deleted its admin-dir entry directly (`rm -rf .git/worktrees/servyy-container`)
   while leaving the workspace directory in place — reproducing "pruned registration,
   surviving directory" without needing to find the exact git subcommand that triggers it
   in the wild.
2. Spun up a second, unrelated workspace on the same repo. Confirmed git reused the freed
   `servyy-container` admin-dir name for it, and that `git status` inside the *first*
   workspace now reported the *second* workspace's branch — the exact hijack described.
3. `close --dry-run` on the first (corrupted) workspace correctly reported `corrupted:
   true` with a reason, and planned `rm -rf` instead of `git worktree remove`.
4. Live `close` on it: agent deregistered, directory removed, **second workspace's
   registration confirmed untouched** (`git worktree list` unchanged) — the critical
   safety property.
5. Committed and pushed a change on the second workspace's branch *without* setting
   upstream tracking; `close`'s embedded repo facts showed `unpushed: 0` (previously would
   have shown `1`, mislabeled).
6. Deleted the second workspace's directory entirely by hand; `close --dry-run` then live
   cleanly deregistered the agent instead of `not_a_spinup_workspace`.
7. Confirmed the empty-`<owner>/`-directory and workspace-root cleanup fired in step 4's
   removal list.

All test branches, the one real GitHub push, and the resulting stale worktree registration
were deleted afterward; servyy-test.lxd was left clean (verified: no leftover workspace
dirs, no leftover agents beyond the hub itself, no stray worktree registrations).

## Follow-up: Bug 2's fix used the wrong command

Found immediately after deploying the above: closing the five real zombie agents in
production reported `session-closed` for all five, but `claude agents --json` still
listed every one of them afterward, unchanged.

**Cause:** the `!existsSync(ws)` branch called `claude stop <id>` only when `isRunning(a)`
was true. Every real zombie has neither `pid` nor `status` at all — `isRunning` was false
for all five, so `stop` was never even attempted, and the branch ledgered a "closed" event
that never touched the actual agent registry. `claude stop` only works on a worker that is
still running; these had already been settled by the daemon's own low-memory retire (not
an explicit `stop`), which evidently leaves a different, still-listed kind of entry behind.

Separately, `claude rm <id>` — the CLI's own documented tool for "an already-exited
session" — failed in production with `couldn't remove <id> — the background service may
be restarting`, consistently, across two different ids and several retries over 40+
seconds, with no corresponding entry in `~/.claude/daemon.log` at all (unlike `claude
agents --json`, which was logging and succeeding throughout). Not root-caused; stopped
retrying against production once it was clearly not a quick transient and reported it
instead of continuing to poke at a live container.

**Fix:** switch to `claude rm <id>`, unconditionally (not gated on `isRunning`), with up
to 4 attempts (3 s apart) and — critically — verify the id is actually gone from `claude
agents` before reporting success, rather than trusting `rm`'s exit code alone. If it's
still listed after all attempts, `close` now fails loudly (`rm_failed`) instead of
ledgering a close that didn't happen.

**Verified on servyy-test.lxd:** the natural low-memory idle-retire that produced the
production zombies doesn't reproduce there (16 GB RAM, miles above the ~1 GB threshold —
confirmed via `free -h`), so the exact shape was reproduced by hand instead: start a real
background session, `kill -9` its actual OS process directly (not `claude stop`, which
deregisters cleanly on its own and would not reproduce the bug), remove its workspace
directory. The result matched production exactly - no `pid`, no `status`, only `state:
"blocked"`. `claude rm` cleanly removed it both directly and through the fixed `close`
action; confirmed gone from `claude agents --json` afterward. Four such repro sessions
were created and fully cleaned up (worktrees, branches, directories) on servyy-test
afterward.

**Not yet re-applied to production** as of this commit: the five pre-existing zombies
(`1987`, `1988`, `2029`, `2042 review pr 2042 scope`, `fix stale eslint code scanning`)
are still listed in production's `claude agents` - the earlier, buggy `close` run against
them ledgered "closed" without actually deregistering anything. Re-running `close --id
<id>` for each once this fix is deployed is the remaining step.

## Not done in this PR

- The admin-dir-uniqueness root cause (see Bug 1's "known limitation").
- Actually closing the five zombie agents already stuck in production (Bug 2's "not done").
- The low-memory retire / RAM question from PR #164 — unrelated to this PR.
