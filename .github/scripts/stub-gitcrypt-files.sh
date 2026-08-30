#!/usr/bin/env sh
# Replace git-crypt encrypted files with YAML stubs so CI tools can parse them.
#
# git-crypt encrypted files are binary in CI (the key is never unlocked) and
# start with a NUL byte (the "\0GITCRYPT\0" magic header). Tools like yamllint,
# ansible-lint and ansible-playbook --syntax-check crash or fail to decode them.
# This script detects those files and overwrites them with a minimal valid YAML
# stub so the tools can proceed.
set -u

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root" || exit 1

git ls-files | grep -E '\.ya?ml$' > /tmp/gitcrypt-lint-files.txt
stubbed=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  # Only consider files git-crypt marks as encrypted.
  filter="$(git check-attr filter -- "$f" 2>/dev/null | awk '{print $3}')"
  [ "$filter" = "git-crypt" ] || continue
  # Encrypted files start with a NUL byte; skip files that are already text.
  first="$(head -c 1 "$f" | od -An -tx1 | tr -d ' \n')"
  [ "$first" = "00" ] || continue
  printf -- '---\n# CI stub for %s\n' "$f" > "$f"
  stubbed=$((stubbed + 1))
done < /tmp/gitcrypt-lint-files.txt
rm -f /tmp/gitcrypt-lint-files.txt

echo "Stubbed ${stubbed} git-crypt encrypted file(s)."