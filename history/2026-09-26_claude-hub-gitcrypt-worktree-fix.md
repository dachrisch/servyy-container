# claude-hub: git-crypt Repos Blocked Every Worktree Dispatch

**Date:** 2026-09-26
**Author:** Claude (via user dachrisch)
**Type:** Bug Fix
**Status:** 🚧 Fixed and verified locally against a real git-crypt fixture; pending servyy-test.lxd deploy and production approval

## Summary

Dispatching a task into any git-crypt-enabled repo (servyy-container included) failed
before a session ever started. `spinup-repo.sh` returned `spinup-blocked` /
`worktree_add_failed`:

```
git-crypt: Error: Unable to open key file - have you unlocked/initialized this repository yet?
error: external filter '"git-crypt" smudge' failed
fatal: <some-encrypted-file>: smudge filter git-crypt failed
```

Discovered by spinning up a `devhub` session to inspect the worktree-dispatch rework
from `history/2026-09-26_claude-hub-worktree-dispatch-rework.md` — the very first
target repo it tried (`dachrisch/servyy-container`) is git-crypt-encrypted, and the
dispatch never got past the worktree step.

## Root Cause

`git-crypt` keeps its unlocked key under the repo's own git-dir
(`.git/git-crypt/keys/...`). A linked worktree gets its **own** git-dir
(`<main-git-dir>/worktrees/<name>/`), which has no git-crypt state at all — it is
never copied or shared by plain `git worktree add`. The moment `add`'s implicit
checkout reaches an encrypted path, the smudge filter can't find a key and the whole
`worktree add` aborts, non-atomically: the branch it was creating (`-b <branch>`)
is left behind on the source repo, and an empty directory is left in the workspace
root.

`skills/spinup-session/scripts/spinup-session.mjs` (vendored from `june-hub`, see
`claude-hub/vendor/VENDORED.md`) does a plain
`git worktree add [-b <branch>] <path> <base>` with no git-crypt awareness — nothing
upstream needed to, since a plugin author has no reason to assume the target repos
are git-crypt-encrypted.

### Confirmed independently, without touching the hub container

Reproduced the identical failure locally in `servyy-container` itself (also
git-crypt-encrypted):

```
$ git worktree add --detach /tmp/wt HEAD
Preparing worktree (detached HEAD d4750d3)
git-crypt: Error: Unable to open key file - have you unlocked/initialized this repository yet?
error: external filter '"git-crypt" smudge' failed
fatal: achim-hoefer/docker-compose.yml: smudge filter git-crypt failed
```

And confirmed the fix mechanism: `git worktree add --no-checkout`, copy
`.git/git-crypt/keys/default` into `<worktree-git-dir>/git-crypt/keys/default`, then
`git checkout HEAD -- .` — the encrypted file decrypts correctly.

## Fix

In `spinup-session.mjs`'s workspace-build loop: before adding a worktree for a repo
whose source has a `<git-dir>/git-crypt` directory, pass `--no-checkout` to
`git worktree add`, copy that directory into the new worktree's own git-dir, then run
an explicit `git checkout HEAD -- .`. Repos without git-crypt take the exact same
code path as before (no `--no-checkout`, no extra checkout).

This is a **local behavior patch** to the vendored file, not a rename — recorded in
`claude-hub/vendor/VENDORED.md`'s new "Local bug fixes" table so a future
re-vendoring pass re-applies it.

## Testing (TDD, per `superpowers:test-driven-development`)

No existing automated-test harness covers these vendored scripts (see
`VENDORED.md` — `scripts/lib/selftest.mjs` is explicitly not vendored). Used the
real `spinup-session.mjs` end-to-end against disposable fixture repos instead of a
mock, driven entirely by CLI flags (`--root`, `--no-fetch`, `--base`, `--no-start`) —
no GitHub network, no config file, no real `claude` session started:

1. **RED** — built a throwaway repo with `git-crypt init` + one encrypted file, ran
   `spinup-session.mjs --repos testowner/gitcrypt-fixture ... --no-start` against
   the pre-fix code. Got `spinup-blocked` / `worktree_add_failed` with the exact
   upstream error, plus the exact leftover artifacts the `devhub` session reported:
   an orphaned local branch and an empty workspace directory.
2. Applied the fix above.
3. **GREEN** — cleaned the fixture (`git worktree prune`, deleted the orphaned
   branch), re-ran the same command: `workspace-ready`, and the checked-out
   `secret.txt` in the new worktree read back as plaintext (`git crypt status`
   correctly reports it `encrypted`, i.e. the filter is live, not merely absent).
4. **Regression** — ran the same script against a second, plain (non-git-crypt)
   fixture repo: unchanged `workspace-ready` behavior, file checked out normally.

## Deployment

1. Branch: `claude/claude-hub-gitcrypt-worktree-fix`
2. Test on `servyy-test.lxd` via
   `./servyy-test.sh --tags "user.docker.repo,user.docker.claude-hub"`, then a real
   dispatch against a git-crypt repo there — pending
3. Production deploy to `codey.lehel.xyz` — pending explicit user approval

## Known follow-up (not fixed here, out of scope)

`git worktree add -b <branch> ...` failing partway through checkout leaves the new
branch behind on the source repo even for non-git-crypt failures (path occupied,
disk full, etc.) — `spinup-repo.sh`'s report against the live `devhub` session found
exactly this residue (`claude/inspect-hub-dispatch` branch + empty directory on
`codey.lehel.xyz`, left over from the blocked attempt, not yet cleaned up). Worth a
`git branch -D`/directory cleanup on any `worktree_add_failed`, independent of this
fix — deferred pending user decision.

## Files Changed

- `claude-hub/vendor/skills/spinup-session/scripts/spinup-session.mjs` — git-crypt-aware
  worktree creation (`gitCryptDir()` helper + `--no-checkout`/key-copy/checkout in the
  build loop)
- `claude-hub/vendor/VENDORED.md` — new "Local bug fixes" table documenting the patch
