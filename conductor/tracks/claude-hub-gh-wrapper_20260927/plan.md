# Plan: claude-hub gh CLI Authentication (Per-Org Wrapper)

**Spec:** ./spec.md
**Branch:** `claude/claude-hub-gh-wrapper`
**Tags used for deployment:** `user.docker.claude-hub`

---

## Phase 1: Branch Setup & Planning

- [x] Task: Create feature branch `claude/claude-hub-gh-wrapper` (7e07d3d)
- [x] Task: Confirm wrapper behavior & verification loop with user (satisfied by `spec.md` approval)
- [x] Task: Plan the concrete file changes (7e07d3d):
  - New: `claude-hub/scripts/gh-wrapper.sh`
  - Modify: `claude-hub/scripts/startup.sh` (install step)
  - New: `ansible/plays/roles/docker_service/molecule/gh-wrapper/{molecule.yml,converge.yml,verify.yml,prepare.yml}`
  - Modify: `.github/workflows/ci.yml` (add `{role: docker_service, scenario: gh-wrapper}` to matrix)
  - New: `history/2026-09-27_claude-hub-gh-wrapper.md`
- [x] Task: **PAUSE** — present this file-change plan and await user validation before writing code (approved by user)
- [x] Task: Conductor - User Manual Verification 'Phase 1: Branch Setup & Planning' (Protocol in workflow.md)

**Checkpoint:** e59b6cd1391f7a23ac3f655fcc05416e5c8a0326

## Phase 2: TDD Implementation (Molecule)

- [x] Task: **RED** — write the `docker_service/gh-wrapper` Molecule scenario (352ce7f) (fake `gh` stub recording argv+`$GH_TOKEN`; test PATs `test-pat-dachrisch`/`test-pat-bumbleflies`) covering: `-R owner/repo`, `--repo=owner/repo`, git-remote-derived owner for both orgs, caller-set `GH_TOKEN` passthrough, and the no-owner-determinable failure case.
- [x] Task: **GREEN** — implement `claude-hub/scripts/gh-wrapper.sh` per spec's owner-resolution rules (352ce7f)
- [x] Task: **GREEN** — wire the install step into `claude-hub/scripts/startup.sh` (352ce7f)
- [x] Task: **GREEN** — run `molecule test --scenario-name gh-wrapper` until it passes. Not run locally (sandbox denies `docker`/`molecule test`); manually verified the real wrapper script against a stubbed real-`gh` binary and real git checkouts first (7 cases / 15 assertions, all passing), then confirmed for real via CI on draft PR [#158](https://github.com/dachrisch/servyy-container/pull/158) — `Molecule Test (docker_service/gh-wrapper)` passed, along with all 23 other CI checks.
- [x] Task: **REFACTOR** — clean up script/tests; run `ansible-lint` and `shellcheck` on the new script (both clean; `yamllint` also clean)
- [x] Task: Add the new scenario to the CI matrix in `.github/workflows/ci.yml` (352ce7f)
- [x] Task: Conductor - User Manual Verification 'Phase 2: TDD Implementation (Molecule)' (Protocol in workflow.md)

**Checkpoint:** 903a4cf50ea45b9a04ece20c6e724b82e0a14f1e

## Phase 3: servyy-test Verification

- [x] Task: Deploy to test env: `cd ansible && ./servyy-test.sh --tags "user.docker.repo,user.docker.claude-hub"` (needed both tags -- `user.docker.claude-hub` alone only re-renders env, doesn't check out the branch), then `docker restart claude-hub.hub` (bind-mounted script change, not a compose/env diff, so compose alone wouldn't recreate the container -- same pattern as the earlier opencode deploy)
- [x] Task: Verify inside `claude-hub.hub`: `gh repo view dachrisch/servyy-container` and a bumbleflies repo view — both succeeded once real repo names were used. `gh auth status` reaches real `gh` with no wrapper error, but real `gh` itself reports "not logged into any hosts" (accepted trade-off, see below)
- [x] Task: Verify a dispatched-session worktree can run `gh pr list` with no `-R` flag — ran inside a throwaway git checkout with `origin` set to `dachrisch/servyy-container`; returned the real PR list (including this track's own PR #158)
- [x] Task: Verify a caller-set `GH_TOKEN` is not overridden, and an unresolvable-owner invocation fails clearly — confirmed: a caller-set (deliberately invalid) `GH_TOKEN` reached real `gh` unmodified (real `gh` rejected the fake token itself, proving the wrapper passed it through untouched); an empty dir with no `-R` and no git repo still hard-fails with the wrapper's own clear error
- [x] Task: Conductor - User Manual Verification 'Phase 3: servyy-test Verification' (Protocol in workflow.md)

**Findings that required going back to the user (both resolved, spec.md updated):**
1. First deploy attempt: `gh repo view dachrisch/servyy-container` and `gh auth status` both hard-failed — positional `owner/repo` args (not just `-R`/`--repo`) needed a detection path, and `gh auth status` has no repo context at all. Fixed with positional-arg detection + an owner-agnostic subcommand skip-list (see 352ce7f.. → a18bcdd, plan Phase 2 note).
2. After that fix, `gh auth status` reached real `gh` correctly but real `gh` itself still reports "not logged in" (skip-list exports no token for `auth`) — accepted as-is per user decision; acceptance criteria in spec.md reworded to not require it report as logged in.
3. Also hit unrelated pre-existing dirty state on servyy-test.lxd (a stale untracked `opencode/scripts/tui.json` from a prior session blocked the branch checkout) and a local git-crypt diff-stat false alarm (`ansible/plays/roles/user/defaults/main.yaml` — confirmed via manual decrypt to be a no-op, unrelated to this track, left untouched).

## Phase 4: Production Approval & Documentation

- [ ] Task: Write `history/2026-09-27_claude-hub-gh-wrapper.md` (problem, solution, files changed, test results)
- [ ] Task: Present Molecule + servyy-test verification results to user
- [ ] Task: **PAUSE** — await explicit "Approved for Production"
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Production Approval & Documentation' (Protocol in workflow.md)

## Phase 5: Production Rollout & Finalization

- [ ] Task: Push branch to origin, open PR
- [ ] Task: Deploy to production: `cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.claude-hub`
- [ ] Task: Post-deploy health check (`gh auth status`, `gh repo view` for both orgs on `claude-hub.hub`)
- [ ] Task: Commit with Conventional Commit message; attach verification summary via `git notes`
- [ ] Task: Update `plan.md` to `[x]` with commit SHA; update `conductor/tracks.md` entry to `[x]`
- [ ] Task: Conductor - User Manual Verification 'Phase 5: Production Rollout & Finalization' (Protocol in workflow.md)
