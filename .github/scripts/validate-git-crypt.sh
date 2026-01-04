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
    "docker-compose.yml filter=git-crypt"
)

for pattern in "${required_patterns[@]}"; do
    if ! grep -q "$pattern" .gitattributes; then
        echo "ERROR: Required pattern '$pattern' not found in .gitattributes"
        exit 1
    fi
done

echo "✓ .gitattributes patterns correct"

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
