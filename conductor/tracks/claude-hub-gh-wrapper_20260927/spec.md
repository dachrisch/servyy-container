# Spec: claude-hub gh CLI Authentication (Per-Org Wrapper)

**Source:** GitHub issue [dachrisch/servyy-container#152](https://github.com/dachrisch/servyy-container/issues/152)
**Type:** Bug fix
**Scope:** claude-hub only (opencode's existing gh-wrapper.sh.j2 is left untouched)

## Overview

Sessions dispatched by claude-hub can `git push` (via `gh-cred-helper.sh`) but cannot use the
`gh` CLI itself — `gh` only reads `GH_TOKEN`/`GITHUB_TOKEN`, neither of which is set in the
container, so commands like `gh pr create` fail with "please run: gh auth login". This adds a
`gh` wrapper — a plain shell script bind-mounted the same way `gh-cred-helper.sh` already is,
not an Ansible template — that resolves the right org PAT (`GITHUB_PAT_DACHRISCH` /
`GITHUB_PAT_BUMBLEFLIES`) per invocation and hands it to the real `gh` binary via `GH_TOKEN`.

## Functional Requirements

1. **New wrapper script** `claude-hub/scripts/gh-wrapper.sh`:
   - If the caller already set `GH_TOKEN` in the environment, leave it untouched and `exec` the
     real `gh` immediately — no owner detection, checked before everything else below.
   - **Owner-agnostic subcommands bypass detection entirely**: if the first argument is
     `auth`, `help`, `config`, `alias`, `extension`, `version`, `--version`, `--help`, or `-h`,
     `exec` the real `gh` immediately with no `GH_TOKEN` override at all (gh's own stored
     `gh auth login` credentials, if any, apply as normal). Found necessary via servyy-test
     verification: `gh auth status` has no `-R`, no positional repo, and — run from
     claude-hub's `checkoutRoot`, not any single repo's worktree — often no git `origin`
     remote either, so the owner-detection gate below always came up empty for it and hard-
     failed a command that has nothing to do with any particular repo.
   - Otherwise, determine an **owner** in this order:
     a. `-R owner/repo` or `--repo owner/repo` (space-separated) or `--repo=owner/repo`,
        scanned anywhere in `gh`'s argv.
     b. Else, a bare positional `owner/repo` argument (exactly one `/`, non-flag): several
        subcommands (`gh repo view`, `gh repo clone`, ...) take the target this way instead of
        via `-R`/`--repo`. Also found via servyy-test verification: `gh repo view
        dachrisch/servyy-container` hard-failed because only the flag form was originally
        handled.
     c. Else, `git config --get remote.origin.url` in the current working directory, parsed for
        a `github.com[:/]<owner>/...` shape.
   - **Owner resolved** (non-empty):
     - `bumbleflies` → export `GH_TOKEN=$GITHUB_PAT_BUMBLEFLIES`.
     - anything else (`dachrisch`, or any other value) → export `GH_TOKEN=$GITHUB_PAT_DACHRISCH`.
   - **Owner not resolved at all** (not an owner-agnostic subcommand, and no `-R`/`--repo`, no
     positional `owner/repo`, no git repo, or no parseable `origin` remote): print a clear
     error to stderr and exit non-zero *without* invoking the real `gh` or exporting any token.
     (No silent fallback for this genuinely-ambiguous case — a deliberate deviation from
     `gh-cred-helper.sh`'s "unknown owner → dachrisch" default, per explicit decision below.)
   - Always end by `exec`-ing the real `gh` binary at its unchanged install path (`/usr/bin/gh`,
     from `apk add github-cli`) with the original argv.

2. **Install step in `claude-hub/scripts/startup.sh`:**
   - Copy `/scripts/gh-wrapper.sh` → `/usr/local/bin/gh`, `chmod +x` (same pattern already used
     for `gh-cred-helper.sh`, just a different destination name). `/usr/local/bin` precedes
     `/usr/bin` in the Alpine image's default `PATH`, so no renaming of the real `gh` binary is
     needed (simpler than opencode's `mv gh gh.real` approach — nothing else on the box
     ever calls `/usr/bin/gh` directly).
   - Runs on every boot; idempotent by construction (copy + chmod, no state to detect).

3. **Testing:** a new Molecule scenario under
   `ansible/plays/roles/docker_service/molecule/gh-wrapper/` that:
   - Installs the wrapper script exactly as `startup.sh` does, with a **fake** `/usr/bin/gh`
     (a stub that records its argv + `$GH_TOKEN` to a file) standing in for the real binary —
     no Alpine/`apk` dependency needed, runs on the existing Ubuntu Molecule image.
   - Sets `GITHUB_PAT_DACHRISCH=test-pat-dachrisch` / `GITHUB_PAT_BUMBLEFLIES=test-pat-bumbleflies`.
   - Exercises: `-R owner/repo`, `--repo=owner/repo`, positional `owner/repo` (both orgs),
     git-remote-derived owner (both orgs), a pre-set `GH_TOKEN` that must survive untouched, the
     owner-agnostic skip-list (`gh auth status` must reach the stub with no `GH_TOKEN`
     override), and the genuine no-owner-determinable case (`gh pr list` with none of the
     above — must exit non-zero and never reach the stub).
   - Added to the CI matrix in `.github/workflows/ci.yml` (`role: docker_service`,
     `scenario: gh-wrapper`).

4. **Manual verification on servyy-test.lxd** (per the issue), after the Molecule scenario
   passes and before production:
   - Deploy with `./servyy-test.sh`.
   - `gh repo view dachrisch/servyy-container` and a bumbleflies repo view — both should succeed
     with no `gh auth login` prompt, using the correct per-org PAT.
   - `gh auth status` reaches the real binary without a wrapper-level error (found and accepted
     during verification: it still reports "not logged into any hosts" / exits non-zero, since
     the owner-agnostic skip-list intentionally exports no token for `auth` — see the accepted
     trade-off below). Not treated as a hard requirement that it report as logged in.
   - In a dispatched session's worktree, confirm `gh pr list` works without `-R`.

5. **History entry** `history/2026-09-27_claude-hub-gh-wrapper.md` documenting the change.

## Non-Functional Requirements

- No change to `opencode`'s existing `gh-wrapper.sh.j2` or its behavior.
- No change to `gh-cred-helper.sh` (git push/pull auth is already working and out of scope).
- Must not weaken security: PATs still only ever live in `claude-hub.env` (git-crypt encrypted)
  and the container's environment — never written to disk in plaintext, never logged.

## Acceptance Criteria

- [ ] New Molecule scenario `docker_service/gh-wrapper` passes locally and in CI.
- [ ] `gh repo view dachrisch/servyy-container` and a bumbleflies-org repo view both succeed
      from inside `claude-hub.hub` with no explicit `GH_TOKEN`.
- [ ] `gh auth status` reaches the real `gh` binary without the wrapper itself erroring out
      (its own "not logged into any hosts" / non-zero exit is accepted — see Functional
      Requirement 1's owner-agnostic skip-list; not a hard requirement that it report logged in).
- [ ] A dispatched session can run `gh pr list` / `gh pr create` in its worktree with no `-R`
      flag and no manual `GH_TOKEN=...` prefix.
- [ ] A caller-set `GH_TOKEN` is never overwritten.
- [ ] Invoking `gh` with no resolvable owner (no `-R`, no `origin` remote) fails clearly instead
      of silently guessing a token.
- [ ] Deployed to production (`--limit codey.lehel.xyz`) only after explicit user approval,
      following servyy-test.lxd verification.

## Out of Scope

- Backporting `-R/--repo` parsing or caller-`GH_TOKEN` preservation into opencode's wrapper.
- Supporting `gh`'s `-Rvalue` attached-shorthand form or an explicit `[HOST/]` prefix in
  `-R`/`--repo` (unused in this environment — always `github.com`, always space- or `=`-separated).
- Any change to how PATs are provisioned/rotated (`ansible/plays/vars/secrets.yml`).
