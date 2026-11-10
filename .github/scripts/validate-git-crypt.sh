#!/bin/bash
set -euo pipefail

echo "=== git-crypt Validation ==="

# Note: .git-crypt directory won't exist in CI (freshly cloned repo)
# This is expected and correct - we validate via .gitattributes instead
if [ ! -d ".git-crypt" ]; then
    echo "ℹ .git-crypt directory not found (expected in CI - repo not unlocked)"
else
    echo "✓ git-crypt initialized"
fi

# Verify .gitattributes exists and has required patterns
if [ ! -f ".gitattributes" ]; then
    echo "ERROR: .gitattributes not found"
    exit 1
fi

required_patterns=(
    "filter=git-crypt"
    "*.yaml filter=git-crypt"
    "*.env filter=git-crypt"
    "*.conf filter=git-crypt"
)

for pattern in "${required_patterns[@]}"; do
    if ! grep -q "$pattern" .gitattributes; then
        echo "ERROR: Required pattern '$pattern' not found in .gitattributes"
        exit 1
    fi
done

echo "✓ .gitattributes patterns correct"

# Compose files must stay PLAINTEXT (removed from git-crypt on 2026-10-29): the
# hosted Renovate app reads the repository through the GitHub API, so an encrypted
# blob hides every `image:` tag in it and image bumps silently stop happening.
# This guards against re-adding the rule out of habit. The safety preconditions are
# listed in .gitattributes and in history/2026-10-29_exposure-guards.md.
compose_probe="traefik/docker-compose.yml"
if git check-attr filter "$compose_probe" | grep -q "git-crypt"; then
    echo "ERROR: $compose_probe is encrypted again."
    echo "       Compose files must stay plaintext so Renovate can bump image tags."
    echo "       Keep secrets in *.env (still encrypted), never inline in a compose file."
    exit 1
fi
echo "✓ compose files are plaintext (Renovate can read image tags)"

# Check critical encrypted files exist
critical_files=(
    "ansible/plays/vars/secrets.yml"
    "ansible/plays/vars/secret_leaguesphere.yaml"
)

for file in "${critical_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "ERROR: Critical encrypted file '$file' not found"
        exit 1
    fi
done

echo "✓ Critical encrypted files present"

# Verify files are tracked by git-crypt
for file in "${critical_files[@]}"; do
    if git check-attr filter "$file" | grep -q "git-crypt"; then
        echo "✓ $file is tracked by git-crypt"
    else
        echo "ERROR: $file is not encrypted or tracked by git-crypt"
        exit 1
    fi
done

# Every blob git-crypt encrypts must actually BE ciphertext, and must not be the
# encryption of an empty file. Both checks read the blob itself, so they need no
# key. Either defect wedges a checkout permanently, without ever showing up in a
# diff a human would notice:
#
#   * A plaintext blob under `filter=git-crypt` (committed with a bypass such as
#     `git -c filter.git-crypt.clean=cat add`) can never look clean to git: the
#     clean filter re-encrypts it, so `git status` reports the file modified
#     forever.
#   * git-crypt 0.7.0 cannot round-trip an empty file: `clean` of empty input
#     emits 0 bytes, while the committed blob is 22 bytes (10-byte header +
#     12-byte nonce, no payload). smudge(22B) = 0B, clean(0B) = 0B != 22B, so
#     every checkout of that path is permanently "modified".
#
# A permanently-modified encrypted file is enough to make
# `git checkout <branch>` / `git pull` abort, so a dev checkout silently stops
# receiving commits while provisioning logs `WARN: update failed` on every boot
# (2026-11-10: ansible/plays/roles/user/defaults/main.yaml pinned codey's
# servyy-container checkout 85 commits behind master; see
# history/2026-11-10_opencode-gitcrypt-empty-file-guard.md).
echo "→ checking that encrypted blobs round-trip..."
bad_blobs="$(mktemp)"
git ls-files | git check-attr --stdin filter | sed -n 's/: filter: git-crypt.*$//p' |
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        size="$(git cat-file -s ":$f" 2>/dev/null || echo 0)"
        header="$(git cat-file blob ":$f" 2>/dev/null | head -c 10 | tr -d '\0')"
        if [ "$header" != "GITCRYPT" ]; then
            printf 'PLAINTEXT-BLOB %s\n' "$f" >> "$bad_blobs"
        elif [ "$size" -eq 22 ]; then
            printf 'ENCRYPTED-EMPTY %s\n' "$f" >> "$bad_blobs"
        fi
    done
if [ -s "$bad_blobs" ]; then
    echo "ERROR: git-crypt blobs that cannot round-trip:"
    while read -r kind file; do
        case "$kind" in
            PLAINTEXT-BLOB)
                echo "  $file — committed as PLAINTEXT while marked filter=git-crypt."
                echo "      Fix: re-add it so the clean filter encrypts it (git rm --cached <file> && git add <file>)."
                ;;
            ENCRYPTED-EMPTY)
                echo "  $file — ENCRYPTED EMPTY FILE (22-byte ciphertext, 0-byte plaintext)."
                echo "      git-crypt cannot re-encrypt it to the same blob, so it is modified forever"
                echo "      and blocks every checkout/pull. Fix: delete it (or give it content)."
                ;;
        esac
    done < "$bad_blobs"
    rm -f "$bad_blobs"
    exit 1
fi
rm -f "$bad_blobs"
echo "✓ encrypted blobs round-trip (no plaintext blobs, no encrypted empty files)"

echo ""
echo "=== git-crypt Validation Passed ==="
exit 0
