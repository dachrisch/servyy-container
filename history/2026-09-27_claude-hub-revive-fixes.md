# claude-hub: revive Fixes to PR #161 Before Merge

**Date:** 2026-09-27
**Author:** Claude (via user dachrisch)
**Type:** Bug Fix (follow-up to an open PR, pre-merge)
**Status:** ✅ Fixed and verified locally; pending CI on the PR branch, then merge/deploy approval

## Summary

`/code-review 161` was run against PR #161 (`fix(claude-hub): hub --name and
stopped-session revive`, branch `claude/claude-hub-issue-159-hub-revive`,
fixes #159) before merging. CI on the PR was already green, but the review
found a confirmed correctness bug plus a related missing safety check, both
in the new `revive --action` fallback added by that PR to
`claude-hub/vendor/skills/session-reaper/scripts/session-reaper.mjs`. Rather
than merge as-is, the user asked to fix these first. This entry documents
that follow-up commit, pushed to the same PR branch.

## Root Cause

**1. Stale-parked-entry lookup.** `revive` computed the ledger entry to act
on with:
```js
const entry = ledger().filter((e) => e.id === o.id && e.event === 'parked').pop();
```
This returns the id's *last-ever* `parked` event, not its *current* state —
if a later `revived` event superseded that park, this line still finds the
old, stale record. That's exactly the scenario PR #161 exists to handle: a
task session parked once, revived, and later going `stopped` again on its
own (its whole `--bg` service shuts down once idle). Hitting `revive` again
would find the stale `parked` entry truthy, skip the PR's new
`respawn-stopped` fallback entirely, and fall into the pre-existing
entry-based path with a stale `resumeSessionId`/`loops` from the *first*
park — never noticing a revive already happened in between.

Two lines above, `last = latestEvent(o.id)` already computes the id's true
latest event (of any type), using `String(...)` coercion for the id
comparison (unlike the buggy line's strict `===`).

**2. Missing hub-safety check in the new fallback.** The new `!entry` branch
only required that `getAgents()` know the id at all before calling `claude
respawn <id>` on it — it applied none of the `kind`/`isHubName`/`samePath`/
`serviceHubId` checks that the sibling `close` action already applies (line
448) before acting on an id. A stopped/exited id that happens to be the hub
(or a non-background session) could be respawned through this path with none
of `close`'s existing protections.

## Fix

In `session-reaper.mjs`:

1. Replaced the `entry` computation to reuse the already-computed `last`
   instead of a second, narrower ledger scan:
   ```js
   const entry = last?.event === 'parked' ? last : null;
   ```
   `last`, when its `event` is `'parked'`, is the exact same shape the old
   filter would have returned — just guaranteed to be the *current* one.

2. Extracted the hub-identity check `close` already had into a shared
   helper, next to `serviceHubId`:
   ```js
   const isHubAgent = (a) => isHubName(a.name) || samePath(a.cwd, checkoutRoot) || (serviceHubId && a.id === serviceHubId);
   ```
   `close` now calls `isHubAgent(a)` in place of its three inlined
   disjuncts (behavior-preserving). The new `revive` fallback gained the
   equivalent guard, checked before the dry-run branch so `--dry-run` also
   reports the refusal instead of "planning" a respawn of the hub:
   ```js
   if (agent.kind !== 'background' || isHubAgent(agent)) {
     fail(EV, 'not_revivable', `${o.id} (${agent.name}) is ${agent.kind !== 'background' ? `a ${agent.kind} session` : 'the hub'} - only stopped background task sessions can be revived this way`, { id: o.id });
   }
   ```

Also updated `claude-hub/vendor/VENDORED.md`'s local-fixes table with a row
documenting this correction to the row PR #161 added.

## Testing

No existing automated-test harness covers these vendored scripts. Verified
with the real script against scratch/real data, entirely via `--dry-run`
(read-only — never calls `claude respawn`/`claude stop`):

1. **Fix 1 (stale entry), reproduced then fixed:**
   - Built a scratch ledger for a synthetic id with a `parked` event
     (`resumeSessionId: STALE-SESSION-ID`) followed by a `revived` event.
   - Ran a throwaway copy of the *pre-fix* line against it: it planned
     `claude --bg --resume STALE-SESSION-ID` — confirming the bug reuses
     stale, pre-revive session data.
   - Ran the *fixed* code against the same ledger: `entry` correctly
     resolved to `null` (latest event is `revived`, not `parked`), routing
     into the `!entry` fallback instead.
2. **Fix 2 (hub safety), verified against a real agent:** using a real
   background job on this machine (`claude agents --json --all`) and
   `--root` set to that job's own `cwd`, `--action revive --id <that id>
   --dry-run` now fails with `not_revivable` instead of planning a respawn.
3. **Regression on `close`:** the same real agent/cwd combination against
   `--action close --id <that id> --dry-run` still fails with
   `not_closable`, confirming the `isHubAgent()` extraction didn't change
   `close`'s existing behavior.
4. `node --check` passes on the modified file.

## Deployment

1. Commit pushed directly to the existing PR branch
   `claude/claude-hub-issue-159-hub-revive` (PR #161).
2. Pending: CI on the updated branch, then merge.
3. Test on `servyy-test.lxd` / production deploy to `codey.lehel.xyz` —
   pending, per PR #161's own stated verification plan and explicit user
   approval for production.

## Known follow-up (not fixed here, out of scope)

The code review also flagged several lower-severity/plausible issues not
covered by this fix: `respawn-stopped` only polls for the *same* id to come
back (no `--resume`/cwd-search fallback like the entry-based path has);
`startup.sh`'s `||` doesn't catch both `claude` invocations failing inside
the detached `tmux` pane; the removed `TODO(verify)` about `--remote-control`
semantics still has no verification against the real CLI; and
`VENDORED.md`'s claim that the `spinup-session.mjs` cwd fallback "matches the
reaper's hub recognition" is inaccurate (the reaper's `decide()` cwd check
compares a different, un-nested path). Left for a separate follow-up.

Separately, and unrelated to PR #161: `ansible/plays/roles/user/defaults/main.yaml`
(git-crypt-encrypted) was found to be a genuine 0-byte file on disk on both
`master` and this PR branch, while `git status` doesn't flag it as modified
at all (its cached index stat entry appears to mask it — `git diff` does
show the mismatch). Flagged to the user; deliberately left untouched here.

## Files Changed

- `claude-hub/vendor/skills/session-reaper/scripts/session-reaper.mjs` —
  fixed `entry` lookup, extracted `isHubAgent()`, added the hub-safety check
  to the `respawn-stopped` fallback
- `claude-hub/vendor/VENDORED.md` — new local-fixes row documenting the
  correction
