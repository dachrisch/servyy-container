---
name: release-please
description: Handle release-please workflows for conventional commit-based releases — creating releases, forcing versions, debugging issues, commit conventions.
---

# Skill: release-please

## Overview

Handles release-please workflows for conventional commit-based releases.

## When to Use

- Creating releases with release-please
- Forcing a specific version release
- Debugging release-please issues
- Understanding commit message conventions

## Commit Message Convention

Release-please uses conventional commits to determine version bumps:

- `fix:` → patch bump (1.0.1)
- `feat:` → minor bump (1.1.0)
- `feat!:` or `BREAKING CHANGE:` → major bump (2.0.0)

## Forcing a Release

When a merge didn't follow conventional commits and didn't trigger a release, add an empty commit with the `release-as` footer:

```bash
git commit --allow-empty -m "chore: trigger release

release-as: X.Y.Z"
```

Replace `X.Y.Z` with the desired version (e.g., `1.12.0`).

## Release-Please Footer Types

| Footer | Purpose |
|--------|---------|
| `release-as: X.Y.Z` | Force a specific version |
| `release-type: simple` | Override release type |
| `changelog-type: skip` | Skip changelog entry |

## Common Workflows

### 1. Normal Release (automated)

Just merge conventional commits. Release-please creates a release PR automatically.

### 2. Force a Patch Release

```bash
git commit --allow-empty -m "chore: force patch release

release-as: 1.11.1"
```

### 3. Force a Minor Release

```bash
git commit --allow-empty -m "chore: force minor release

release-as: 1.12.0"
```

### 4. Skip a Release

```bash
git commit --allow-empty -m "chore: skip release

release-type: skip"
```

## Troubleshooting

### Release PR not created

1. Check if commits follow conventional format
2. Verify the `release-please-action` is running in GitHub Actions
3. Check the action logs for errors

### Wrong version bumped

Use `release-as` footer to force the exact version needed.

## References

- [Release-Please Documentation](https://github.com/googleapis/release-please)
- [Conventional Commits](https://www.conventionalcommits.org/)
