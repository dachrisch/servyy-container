# claude-hub: Per-Org `gh` CLI Wrapper

**Date:** 2026-09-27
**Author:** Claude (via user dachrisch)
**Type:** Bug fix
**Status:** ✅ Merged (PR [#158](https://github.com/dachrisch/servyy-container/pull/158),
`3c2bb1d`, 23/23 CI checks green) and deployed to production `codey.lehel.xyz` —
`claude-hub.hub` restarted, reached `healthy`, hub tmux session resumed cleanly;
`gh repo view` verified working for both orgs with the correct PAT.

## Summary

Sessions dispatched by `claude-hub` could `git push`/`git pull` (via
`gh-cred-helper.sh`) but couldn't use the `gh` CLI itself: `gh` only reads
`GH_TOKEN`/`GITHUB_TOKEN`, and neither was set, so `gh pr create` and similar
failed with "please run: gh auth login". Seen 2026-09-26 on
leaguesphere#1987/#1988 — both pushed their branches but couldn't open PRs;
the hub opened them by hand with `GH_TOKEN=$GITHUB_PAT_DACHRISCH gh ...`.
Reported as [issue #152](https://github.com/dachrisch/servyy-container/issues/152).

Adds `claude-hub/scripts/gh-wrapper.sh`: a plain shell script, bind-mounted
the same way as `gh-cred-helper.sh` (not an Ansible template, unlike
opencode's equivalent), that resolves the target repo owner per invocation
and exports `GH_TOKEN` from the matching PAT (`GITHUB_PAT_DACHRISCH` /
`GITHUB_PAT_BUMBLEFLIES`) before handing off to the real `gh` binary.

Full spec/plan: `conductor/tracks/claude-hub-gh-wrapper_20260927/`.

## Design

- **Owner resolution**, in order: `-R`/`--repo` flag (space- or `=`-form) →
  bare positional `owner/repo` argument (`gh repo view owner/repo` etc.) →
  the cwd's git `origin` remote. `bumbleflies` → `GITHUB_PAT_BUMBLEFLIES`;
  anything else → `GITHUB_PAT_DACHRISCH` (matches `gh-cred-helper.sh`'s
  existing unknown-owner convention).
- **A caller-set `GH_TOKEN` is never overridden**, checked before anything
  else.
- **Owner-agnostic subcommands** (`auth`, `help`, `config`, `alias`,
  `extension`, `version`, `--version`, `--help`, `-h`) bypass owner
  detection entirely and get no `GH_TOKEN` override — these have no repo
  context for the wrapper to resolve.
- **Genuinely ambiguous invocations hard-fail** with a clear stderr message
  instead of silently guessing a token — a deliberate deviation from
  `gh-cred-helper.sh`'s "unknown → dachrisch" default for this one case,
  weighed explicitly against reverting to that default (see below).
- Installed by `startup.sh` at `/usr/local/bin/gh`, which precedes the
  `apk`-installed `/usr/bin/gh` on `PATH` in the Alpine image — no
  rename-to-`.real` dance needed (unlike opencode's wrapper), since nothing
  else on the box calls `/usr/bin/gh` directly.
- **Scoped to claude-hub only.** opencode's existing
  `ansible/plays/roles/opencode/templates/bin/gh-wrapper.sh.j2` doesn't need
  positional-argument parsing or caller-`GH_TOKEN` preservation and was left
  untouched, per an explicit scoping decision (see below).

## Decisions settled with the user

1. **Scope**: claude-hub only, not backported to opencode's wrapper.
2. **Testing mechanism**: a new Molecule scenario
   (`ansible/plays/roles/docker_service/molecule/gh-wrapper/`) rather than a
   plain shell test script — even though the wrapper itself isn't an
   Ansible template, Molecule was chosen to keep this inside the same
   CI/local-test framework the rest of the repo uses. It boots a container,
   installs the wrapper exactly as `startup.sh` does, and drives it against
   a fake real-`gh` stub that records its invocation.
3. **No-owner-determinable fallback**: fail with a clear error rather than
   default to the dachrisch PAT — chosen up front, then **revisited twice**
   after concrete evidence from live verification (see below) rather than
   reverted outright:
   - First conflict found: the "fail" rule blocked `gh auth status`, which
     has no repo context at all — resolved by adding an owner-agnostic
     subcommand skip-list instead of reverting the fallback rule generally.
   - Second conflict found: skip-listed `auth` still gets no token, so real
     `gh auth status` reports "not logged in" / exits non-zero — accepted
     as-is (see "Known, accepted gaps" below) rather than special-casing a
     dachrisch default for `auth` specifically.

## Two real gaps found and fixed during `servyy-test.lxd` verification

The Molecule scenario's first version only ever exercised `-R`/`--repo` and
git-remote-derived detection — both real, and neither anticipated until
live verification surfaced them:

1. **`gh repo view dachrisch/servyy-container` hard-failed.** `gh repo
   view`/`gh repo clone` take the target repo as a *positional* argument,
   not via `-R`/`--repo`, which the wrapper never scanned for. Fixed by
   scanning for a bare, non-flag, exactly-one-slash argument as a second
   detection method.
2. **`gh auth status` hard-failed.** It has no `-R`, no positional repo,
   and — run from claude-hub's `checkoutRoot` rather than any single repo's
   worktree — no git `origin` remote either, so owner detection always came
   up empty. Fixed with the owner-agnostic subcommand skip-list described
   above.

Both fixes: commit `a18bcdd` (in-branch). Molecule scenario extended with 3
more cases (positional owner/repo × 2 orgs, the skip-list); local manual
verification (12 cases against the real script + a stubbed real-`gh` binary
+ real git checkouts, all passing) done before each servyy-test redeploy,
since this session's sandbox has no direct Docker access to run
`molecule test` itself locally — CI (GitHub Actions, which does have Docker)
was the actual gate both times.

## Known, accepted gaps

- **`gh auth status` still reports "not logged in" / exits non-zero.** The
  wrapper itself no longer errors (real `gh` is reached), but the
  owner-agnostic skip-list exports no token for `auth`, so real `gh` has
  nothing to authenticate with. Accepted trade-off — the actual functional
  need (repo-scoped commands like `pr create`/`repo view`/`issue list`) all
  work; `spec.md`'s acceptance criteria were rewored to reflect this rather
  than special-casing a dachrisch default for `auth`.
- **`-Rvalue` attached shorthand and an explicit `[HOST/]` prefix are not
  supported** in `-R`/`--repo` parsing — out of scope, unused in this
  environment (always `github.com`, always space- or `=`-separated).
- **opencode's wrapper is unchanged** — it doesn't need positional-argument
  parsing or caller-`GH_TOKEN` preservation for its own use, and backporting
  was explicitly declined to keep this change scoped.

## Files Changed

- `claude-hub/scripts/gh-wrapper.sh` (new) — the wrapper itself.
- `claude-hub/scripts/startup.sh` — installs the wrapper at
  `/usr/local/bin/gh` (new step 5; steps renumbered 5–9).
- `ansible/plays/roles/docker_service/molecule/gh-wrapper/{molecule,converge,verify,prepare}.yml`
  (new) — the Molecule scenario.
- `.github/workflows/ci.yml` — added `{role: docker_service, scenario:
  gh-wrapper}` to the CI matrix.
- `conductor/tracks/claude-hub-gh-wrapper_20260927/{spec,plan,metadata}` —
  full track history, including both mid-flight spec revisions.

## Testing

**Local (this session, no Docker access):**
- `shellcheck`: clean on both scripts.
- `ansible-lint` / `yamllint`: clean on the new Molecule scenario and the CI
  workflow change.
- Manual logic check: the real `gh-wrapper.sh`, run directly against a
  stubbed real-`gh` binary (records argv + `$GH_TOKEN`) and real git
  checkouts — 12 cases, all passing (both PAT-routing paths × both orgs,
  positional argument × both orgs, caller-`GH_TOKEN` passthrough, the
  owner-agnostic skip-list, and the genuine hard-fail case).

**CI (PR #158, GitHub Actions):**
- All 23 checks green on both the initial implementation commit and the
  positional-arg/skip-list fix commit, including
  `Molecule Test (docker_service/gh-wrapper)`.

**servyy-test.lxd (live):**
- Deploy mechanism: `./servyy-test.sh --tags "user.docker.repo,user.docker.claude-hub"`
  (the `user.docker.repo` tag is required to actually check out the branch —
  `user.docker.claude-hub` alone only re-renders the env file), followed by
  `docker restart claude-hub.hub` (the wrapper is a bind-mounted script
  change, not a compose/env diff, so `docker compose up -d` alone doesn't
  recreate the container — same pattern as a prior opencode deploy).
- `gh repo view dachrisch/servyy-container`: succeeds, real API data.
- `gh repo view bumbleflies/web`: succeeds, real API data, correct PAT.
- `gh pr list` in a throwaway git checkout with `origin` set to
  `dachrisch/servyy-container`, no `-R`: succeeds, returned the real PR
  list including this track's own PR #158.
- A deliberately-invalid caller-set `GH_TOKEN`: passed through untouched —
  confirmed by real `gh` rejecting that exact fake value itself, not the
  wrapper's own PAT.
- No `-R`, no git repo (e.g. an empty `/tmp` dir): hard-fails with the
  wrapper's own clear error, never reaches real `gh`.

**Incidental, unrelated to this change:**
- A stale untracked `opencode/scripts/tui.json` left on `servyy-test.lxd`
  from a prior session blocked the branch checkout; removed (harmless
  generated file, test host only).
- A local `git diff --stat` showing `ansible/plays/roles/user/defaults/main.yaml`
  as "Bin 22 → 0 bytes" turned out to be a git-crypt filter display
  artifact (ciphertext blob size vs. smudged working-tree size), not a real
  change — confirmed via `git cat-file HEAD:<path> | git-crypt smudge`
  decrypting to the same empty content already on disk. Left untouched.

## Future Enhancements

- If opencode's wrapper ever needs `-R`/positional parsing or
  caller-`GH_TOKEN` preservation, extract the shared owner-resolution logic
  instead of duplicating this fix into both wrappers independently.
- If a third GitHub org is ever added to this infrastructure, both
  `gh-cred-helper.sh` and this wrapper's `case "$owner"` need the new PAT
  branch added in parallel.
