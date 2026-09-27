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

- [ ] Task: Deploy to test env: `cd ansible && ./servyy-test.sh --tags user.docker.claude-hub`
- [ ] Task: Verify inside `claude-hub.hub`: `gh auth status`, `gh repo view dachrisch/servyy-container`, and a bumbleflies-org repo view
- [ ] Task: Verify a dispatched-session worktree can run `gh pr list` with no `-R` flag
- [ ] Task: Verify a caller-set `GH_TOKEN` is not overridden, and an unresolvable-owner invocation fails clearly
- [ ] Task: Conductor - User Manual Verification 'Phase 3: servyy-test Verification' (Protocol in workflow.md)

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
