# 2026-11-10 — git-crypt cannot round-trip an empty file, and it wedged a checkout

## Why

Follow-up to `history/2026-11-10_opencode-gitcrypt-provision-repair.md`. That
incident left one unexplained artifact: after the ciphertext in
`/root/dev/dachrisch/servyy-container` was repaired, `git status` still reported

```
 M ansible/plays/roles/user/defaults/main.yaml
```

with `Bin 22 -> 0 bytes` — and that single permanently-modified file made every
`git checkout <branch>` / `git pull` in the clone abort, so `provision-dev.sh`
logged `WARN: update failed for dachrisch/servyy-container` on every boot and
the checkout sat on `0415414` while `origin/master` was 85 commits ahead.

## Root cause — an encrypted *empty* file

The path is marked `filter=git-crypt` by the blanket `*.yaml` rule, and its
committed blob is **22 bytes**: `\0GITCRYPT\0` (10) + 12-byte HMAC nonce, i.e.
the encryption of **zero bytes** of plaintext.

git-crypt 0.7.0 cannot reproduce that blob from the plaintext:

```
$ printf '' | git-crypt clean | wc -c
0                     # exit 0, no output at all
$ git cat-file blob :<path> | git-crypt smudge | wc -c
0                     # decrypts to empty, as expected
```

So the round trip is `smudge(22 B) = 0 B`, `clean(0 B) = 0 B ≠ 22 B`. Git's
clean-filtered worktree can therefore never equal the committed blob and the
path is modified forever, on every clone, for everyone. Because git's
up-to-date check for merges is stat/size based (`22` in the index vs `0` on
disk), no filter override helps: even
`git -C <clone> -c filter.git-crypt.clean=cat pull --ff-only` still aborts with
`Your local changes to the following files would be overwritten by merge`.

Upstream had already worked around it on 2026-10-30 (`0ffe96a`, "remove the dead
user/defaults/main.yaml, keep the dir via .gitkeep" — the file was functionally
empty and both deploys ran fine without it), but this clone could not advance
far enough to receive that commit: the deletion only lands *after* the pull that
the phantom modification blocks.

## Fix

1. **Unblocked the codey checkout** (operational, no repo change): the only
   tracked local modification was that empty file, so
   `git -C /root/dev/dachrisch/servyy-container reset --hard origin/master`
   discarded the phantom modification, fast-forwarded to `0e604dc`, and removed
   the file (deleted upstream). Untracked files, all local branches and all five
   stashes were untouched. Provisioning's own update path (`fetch` +
   `checkout master` + `pull --ff-only`) now succeeds.
2. **CI guard** in `.github/scripts/validate-git-crypt.sh` — after the existing
   attribute checks, every tracked path carrying `filter=git-crypt*` is now
   checked against its *blob*, which needs no key:
   - the blob must start with `\0GITCRYPT\0` (catches plaintext blobs committed
     through a `-c filter.git-crypt.clean=cat` bypass, which are equally
     permanently-modified);
   - the blob must not be exactly 22 bytes (an encrypted empty file, the case
     above).
   Both failures print per-file remediation (re-add through the clean filter, or
   delete/give the empty file content) and fail the job.
3. `opencode/scripts/AGENTS.md` — the diagnosis for "update failed + a modified
   encrypted file": check the blob size, don't try filter overrides, remedy is
   `git reset --hard origin/master`, and upstream should delete the empty file.

## Verification

```
$ bash .github/scripts/validate-git-crypt.sh
...
→ checking that encrypted blobs round-trip...
✓ encrypted blobs round-trip (no plaintext blobs, no encrypted empty files)
=== git-crypt Validation Passed ===
```

The rule applied to the old commit's blob, and to current master:

```
0415414  size=22 header=GITCRYPT -> ENCRYPTED-EMPTY     # would have failed CI
0e604dc  path absent (deleted upstream) -> ok
```

Live checkout after the unblock:

```
HEAD is now at 0e604dc fix(opencode): repair broken git-crypt checkouts during provisioning (#282)
?? .claude/settings.local.json
?? ansible/plays/vars/.servyy_container_deploy_key.pub
--- secrets: --- create_user: cda
$ git fetch && git checkout master && git pull --ff-only   # succeeds
```

A repo-wide scan of current master finds **no** plaintext-blob and no
encrypted-empty file; the guard is a ratchet, not a remediation backlog.

## Notes

- `dachrisch/devhub` still fails its provisioning update, for an unrelated
  reason: it has uncommitted tracked modifications of its own. Not addressed
  here.
- Anything that *writes* an empty file into an encrypted path recreates this
  wedge. If such a file is ever needed, it must be exempted in `.gitattributes`
  (`<path> !filter !diff`), not encrypted.
