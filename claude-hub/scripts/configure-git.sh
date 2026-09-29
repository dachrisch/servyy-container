#!/bin/sh
# Global git configuration for the claude-hub container: identity, the
# per-org GitHub credential helper, and SSH->HTTPS URL rewriting. Called from
# startup.sh on every boot (after gh-cred-helper.sh has been installed to
# $CRED_HELPER); kept as its own script so Molecule can run exactly this file
# (ansible/plays/roles/docker_service/molecule/gh-wrapper). Idempotent.
#
#   configure-git.sh [cred-helper-path]
set -eu

CRED_HELPER="${1:-/usr/local/bin/gh-cred-helper.sh}"

# Identity for commits made from inside this container.
git config --global user.name "claude-hub"
git config --global user.email "claude-hub@codey.lehel.xyz"
git config --global --replace-all safe.directory '*'

# GitHub HTTPS auth. Every form of credential.helper (bare name, absolute
# path, or "!"-prefixed) is executed via a shell (sh -c) per
# gitcredentials(7); a plain absolute path like this one is used as-is.
git config --global credential.https://github.com.helper "$CRED_HELPER"
# credential.useHttpPath defaults to false, which makes git strip the "path"
# attribute (the owner/repo.git part) from every credential request -- without
# it gh-cred-helper.sh's owner="${path%%/*}" routing always sees an empty path
# and always falls into its default case. Required for per-org PAT selection.
git config --global credential.useHttpPath true

# SSH -> HTTPS rewrite. The /root/dev checkouts live on the codey_dev_checkouts
# volume shared with opencode, whose provision-dev.sh re-points every origin to
# git@github.com:<owner>/<repo>.git on each opencode boot (opencode has an SSH
# key; this container has neither a key nor an ssh binary). Worktrees share
# their source repo's config, so dispatched sessions inherited that SSH origin
# and every fetch/push failed with "cannot run ssh". Rewriting in *this
# container's* global config fixes it for any remote form without touching the
# shared checkouts' own .git/config -- opencode keeps its SSH origins (and its
# own reverse https->ssh insteadOf), git-crypt is unaffected (it is a
# smudge/clean filter, independent of the transport). insteadOf applies to
# both fetch and push. See history/2026-09-29_claude-hub-ssh-rewrite-and-bg-retire.md.
# Reset, then add both SSH spellings, so repeated boots never accumulate
# duplicate values (unset-all exits 5 when the key does not exist yet).
git config --global --unset-all url.https://github.com/.insteadOf || true
git config --global --add url.https://github.com/.insteadOf git@github.com:
git config --global --add url.https://github.com/.insteadOf ssh://git@github.com/
