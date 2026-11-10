# 2026-11-10 — OpenCode provisioning could not repair a broken git-crypt checkout

## Why

`/root/dev/dachrisch/servyy-container` on codey (the checkout OpenCode sessions
work in) had four git-crypt-encrypted files holding **ciphertext** in its working
tree while `git status` looked clean, so `ansible/plays/vars/secrets.yml`,
`traefik/traefik.yaml`, `traefik/dynamic.yaml` and `achim-hoefer/nginx/default.conf`
read as `\0GITCRYPT\0…` to anything that opened them. That is indistinguishable
from a locked repo, and it was reported as "the servy repo on codey is
git-crypt locked".

It was not locked: `.git/git-crypt/keys/default` was present, `git-crypt status`
exited 0, and `git-crypt smudge` on `HEAD:ansible/plays/vars/secrets.yml`
decrypted correctly. Checking out the files again through the real filter
reproduces plaintext.

## Root cause

Three independent things, in order:

1. **2026-10-31** — git operations on the Traefik work were run with the filters
   bypassed (`git -c filter.git-crypt.smudge=cat -c filter.git-crypt.clean=cat
   rebase/checkout/merge`). `smudge = cat` makes git write the *ciphertext blob*
   verbatim instead of decrypting it, so the four rewritten files became
   ciphertext on disk. Later checkouts never touched them again (git's stat
   cache considers them unchanged), so the ciphertext persisted silently.
2. **2026-11-10 20:39** — a session investigated the symptom, probed
   `./.git-crypt/` (wrong path; git-crypt state lives in `.git/git-crypt/keys/`),
   saw it missing, concluded "locked", and pinned the workaround into the repo's
   local config: `git config filter.git-crypt.smudge cat`. That makes every
   *future* checkout write ciphertext too.
3. **`provision-dev.sh` could not fix it.** Its unlock guard was

   ```sh
   if git -C "$dest" config --local --get filter.git-crypt.smudge >/dev/null 2>&1
   ```

   i.e. it tested only that the config *exists*. `cat` satisfies that, so every
   container boot logged `already git-crypt unlocked` and skipped the one step
   that would repair the checkout. Re-running provisioning was a no-op that
   actively certified the broken state (and would still have switched the clone
   onto `master` and pulled).

## Fix

- `opencode/scripts/provision-dev.sh` — a new `ensure_git_crypt` helper runs
  **before** the update step (a checkout holding ciphertext shows up as locally
  modified, which is what made `git checkout <branch>` / `pull` fail). It treats
  a checkout as healthy only when all three hold:
  - `.git/git-crypt/keys/default` exists;
  - the local `filter.git-crypt.smudge` matches `*git-crypt*`;
  - no encrypted file in the working tree still begins with the `\0GITCRYPT\0`
    envelope.

  Whatever is wrong gets repaired in the least destructive order: hand-set
  filters are rewritten to the real commands, a missing key is installed with
  `git-crypt unlock "$CRYPT_KEY"` (which also rewrites filters and re-checks-out
  every encrypted path), and finally each file still holding ciphertext is
  re-smudged with `git checkout -- <path>`. That last step is safe by
  construction: a file whose content is the ciphertext envelope cannot also hold
  an uncommitted plaintext edit. Anything still broken is reported as a WARN
  (e.g. a genuinely dirty checkout) rather than guessed at.
- `claude-hub/scripts/provision-repos.sh` — the same helper and ordering, for
  the "KEEP IN SYNC" contract between the two provisioning scripts (the
  claude-hub service is production-disabled; this is textual parity).
- `ansible/plays/roles/opencode/tasks/main.yml` — *Deploy OpenCode dev
  provisioning script* now notifies `restart opencode container`. Without it a
  `--tags user.docker.opencode` deploy copied the new script and nothing ran it
  until some unrelated restart. The handler uses `docker compose restart`
  (`state: restarted`), which only re-execs the entrypoint — it cannot recreate
  the container (see `handlers/main.yml`).
- `opencode/scripts/AGENTS.md` — records the `.git-crypt/` vs
  `.git/git-crypt/keys/` trap, how to diagnose before declaring a repo locked,
  and a hard prohibition on `-c filter.git-crypt.smudge=cat
  -c filter.git-crypt.clean=cat` (the origin of the ciphertext in step 1).

## Verification

Rehearsal on a scratch clone inside the container (`git clone` of the live
checkout, unlocked properly, then broken into exactly the live shape: `smudge =
cat` plus two files written as raw ciphertext), running the `ensure_git_crypt`
helper extracted verbatim from the new script:

```
== break it exactly like the live clone:
   smudge=cat   secrets head: ^@GITCRYPT^@
   dirty files: 3
== run repaired ensure_git_crypt()
[test] restored git-crypt filters for scratch
[test] re-smudged scratch:ansible/plays/vars/secrets.yml
[test] re-smudged scratch:traefik/traefik.yaml
[test] scratch git-crypt working tree OK
== assertions
   smudge now: /usr/bin/git-crypt smudge
   secrets head: --- create_user: cda
```

Static checks:

```
sh -n opencode/scripts/provision-dev.sh                # OK
sh -n claude-hub/scripts/provision-repos.sh            # OK
shellcheck -s sh <both scripts>                        # no new findings
                                                       # (3 pre-existing SC2015 infos remain)
yamllint -c .yamllint.yml plays/roles/opencode/tasks/main.yml
                                                       # 1 pre-existing line-length warning (line 90)
ansible-playbook servyy.yml --syntax-check -i testing   # OK
```

The key is safe to re-install: `GIT_CRYPT_KEY_B64` decodes to sha256
`c24dc4cc88dd56be5f378e2fda41e40c49da5cd39b9018f8ddd33ef31fe80724`, identical to
the key already installed in both clones, so `git-crypt unlock` rewrites the same
key rather than a different one.

Post-deploy verification (`--tags user.docker.opencode`, which now restarts the
container, so `startup.sh` → `provision-dev.sh` ran the repair):

```
[provision-dev] re-smudged dachrisch/servyy-container:ansible/plays/roles/user/defaults/main.yaml
[provision-dev] re-smudged dachrisch/servyy-container:ansible/plays/vars/secrets.yml
[provision-dev] re-smudged dachrisch/servyy-container:traefik/dynamic.yaml
[provision-dev] re-smudged dachrisch/servyy-container:traefik/traefik.yaml
[provision-dev] dachrisch/servyy-container git-crypt working tree OK
```

```
$ git -C /root/dev/dachrisch/servyy-container config --local --get filter.git-crypt.smudge
/usr/bin/git-crypt smudge
$ head -2 ansible/plays/vars/secrets.yml
---
create_user: cda
$ # encrypted paths still holding ciphertext
0
$ git status --short
 M ansible/plays/roles/user/defaults/main.yaml
?? .claude/settings.local.json
?? ansible/plays/vars/.servyy_container_deploy_key.pub
```

`servyy-deploy-master` was untouched (still `"git-crypt" smudge`, plaintext
secrets) and `https://code.lehel.xyz/health` is 200 after the restart.

## Rollback

Revert this commit and re-deploy. No checkout is deleted by the change; the worst
case after a boot is that a clone sits on its default branch (`master`) rather
than a feature branch, which is pre-existing provisioning behaviour.

## Notes / follow-ups (not in this change)

- **`ansible/plays/roles/user/defaults/main.yaml` still blocks the update step.**
  It is committed as *plaintext* while `.gitattributes` marks every `*.yaml` for
  encryption ("git-crypt drift", first recorded in
  `history/2026-10-06_queen-prod-enablement.md`), so `git` always reports it as
  modified: `provision-dev.sh` logs `WARN: update failed for
  dachrisch/servyy-container` and the checkout stays at `0415414` while
  `origin/master` is `d1d9ea3` (85 commits). Needs a decision in
  `servyy-container` itself: re-commit that file as proper ciphertext, or drop
  the encryption attribute for it in `.gitattributes`. `devhub` has uncommitted
  tracked changes of its own and fails its update for the same reason.
- The only copies of the git-crypt symmetric key are the three
  `.git/git-crypt/keys/default` files plus `GIT_CRYPT_KEY_B64` in the service
  env; the exported `/tmp/opencode/gitcrypt.key` is gone and there is no
  `~/.git-crypt`. A durable off-clone backup is still missing.
- `servyy-container`'s own `AGENTS.md` would benefit from the same
  "don't bypass the filters" warning — needs a PR in that repo.
- Linked worktrees still have no git-crypt state of their own; unchanged here,
  documented in `history/2026-09-26_claude-hub-gitcrypt-worktree-fix.md`.
