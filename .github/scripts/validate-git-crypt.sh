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

echo ""
echo "=== git-crypt Validation Passed ==="
exit 0
