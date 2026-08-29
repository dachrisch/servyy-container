---
name: opencode-contribution
description: Manage code changes, testing, and PR workflow for opencode projects
triggers:
  - contrib
  - develop
  - code
  - "add feature"
  - "fix bug"
  - pull request
  - "branch"
delegates_to:
  - opencode-deployment
  - opencode-dependency
reads:
  - CONTRIBUTING.md
  - README.md
  - .github/workflows
  - package.json
  - tsconfig.json
  - jest.config.js
---

# OpenCode Contribution Workflow

This skill manages code changes, testing, and PR creation for opencode projects.

## Pre-Work Checks

When starting work on an opencode project:

1. **Verify current branch state**
   ```bash
   git status
   git log --oneline origin/master..HEAD
   ```

2. **If NOT on master:**
   - Check if branch is current: `git log --oneline -1` vs remote master
   - Ask: "Should I rebase on latest master or create a fresh branch?"
   - Prefer: **fresh branch from current master** for isolation

3. **Read project guidelines** (in order of existence)
   - `CONTRIBUTING.md` - PR requirements, testing strategy, release process
   - `.github/PULL_REQUEST_TEMPLATE.md` - PR structure expectations
   - `README.md` - Development setup, local testing

## Branch Workflow

**ALWAYS start from master:**
```bash
git fetch origin
git checkout master
git pull origin master
git checkout -b claude/feature-description
```

**Why:** Ensures clean history, no merge conflicts, fresh view of codebase.

## Commit Message Format

Read project for convention (look at recent commits via `git log --oneline -10`).

Common patterns:
- `feat: add user authentication`
- `fix: resolve memory leak in worker pool`
- `refactor: simplify async error handling`
- `docs: update installation guide`
- `test: add coverage for payment flow`

## PR Requirements

Check project's `CONTRIBUTING.md` and `.github/PULL_REQUEST_TEMPLATE.md` for:
- Minimum test coverage expectations
- Lint/format enforcement (eslint, prettier, etc.)
- Code review requirements (# of approvals)
- Deployment/release process (automatic vs. manual)
- Documentation updates needed

## Testing

Before submitting PR, run project's test suite:
```bash
npm test           # Common: Jest
npm run lint       # Linting
npm run build      # Compilation check
```

Verify in local environment:
- Golden path works
- Edge cases handled
- No regressions in other features
- Logs/errors are clear

## When to Delegate

- **To opencode-deployment skill:** If work includes "deploy this to prod" or production error investigation
- **To opencode-dependency skill:** If work spans both service code AND ansible deployment changes

## Common Pitfalls

- ❌ Working on stale branch without rebasing
- ❌ Not running tests before PR
- ❌ Assuming PR requirements (always read CONTRIBUTING.md)
- ❌ Mixing unrelated changes in one PR (one feature per PR)

✅ **Verify before closing:**
- [ ] Tests pass locally
- [ ] Branch is fresh from master
- [ ] Commit messages are clear
- [ ] No unrelated files in changeset
