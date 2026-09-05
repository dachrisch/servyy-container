# OpenCode Volume Cleanup (2026-09-05)

## Problem

Follow-up to the same day's devhub-404/disk-pressure incident
(`2026-09-05_devhub-404-codey-swap-resize.md`): after freeing disk via the swap
resize, the opencode docker volume (`opencode_opencode_root`) itself was still
carrying ~6.7GB of avoidable weight on codey:

- ~3.6GB of **orphaned flat-layout repo clones** under `/root/dev/<repo>` — a
  prior discovery generation (`opencode/scripts/provision-dev.sh`) used to
  clone repos directly under `$DEV_DIR`; the current topic-based discovery
  only ever writes to `$DEV_DIR/<owner>/<repo>`, so the old flat clones were
  never touched again. Confirmed stale via commit/remote/mtime comparison
  (e.g. flat `/root/dev/devhub` stuck at an old commit vs. current
  `/root/dev/dachrisch/devhub`), or the GitHub repo itself renamed
  (`energy`→`energy.consumption`, `groceries`→`groceries-order-tracking`) or
  gone.
- ~1.7GB of session **checkpoint snapshot repos** (`~/.local/share/opencode/
  snapshot/*/objects/pack/*`), never garbage collected.
- ~1.4GB of unbounded **npm package cache** (`~/.npm/_cacache`), no eviction
  policy of its own, fully regenerable.

## Solution

1. **`opencode/scripts/provision-dev.sh`** — after the discovery/clone loop,
   walk top-level entries of `$DEV_DIR`, skip known org dirs (`dachrisch`,
   `bumbleflies`, captured once as `ORGS` and reused in both places), and
   `rm -rf` anything else containing a `.git` dir. Runs on every container
   boot, so it also guards against the same drift recurring if the discovery
   scheme changes again.
2. **`opencode/scripts/prune-sessions.py`** — extended the existing session
   DB / tool-output pruning job with `prune_snapshots()`: removes checkpoint
   repos under `snapshot/<project>/<repo>/` whose newest file mtime is older
   than the same `OPENCODE_PRUNE_HOURS` cutoff already used for sessions.
3. **`opencode/docker-compose.yml`** — new weekly Ofelia job-exec label
   (`npm-cache-clean`, Sundays 05:00) running `npm cache clean --force`.

### Incidental fixes needed to ship the above

- **git-crypt drift** (two files, unrelated to this change but blocking its
  deployment): `opencode/docker-compose.yml` and `ansible/plays/roles/user/
  defaults/main.yaml` were both stored as plaintext in git history despite
  `.gitattributes` marking them for encryption (committed before that
  pattern took effect). Fixed via git-crypt's own `status -f` remedy
  (re-stages a properly encrypted blob going forward; does not rewrite
  history — no secrets were in either file, so not urgent to scrub the old
  plaintext blobs, would need a separate filter-repo/BFG pass if ever
  wanted). Commits `6caa1b0`, `08a4f4a`.
- **`ansible/plays/roles/user/tasks/includes/repository.yml`** — added an
  explicit `git reset --hard` on tracked paths right before the repo
  clone/checkout task. Root cause: the opencode role's docker-compose.yml
  deploy task writes plaintext directly to a git-tracked path (bypassing
  git); combined with git-crypt's non-deterministic encryption (random IV
  per encrypt), this left the working tree looking "locally modified" to
  git on every subsequent operation, which blocked checking out a
  not-yet-locally-known branch (ansible's git module `force: true` only
  auto-discards mods when updating an *existing* local branch, not when
  creating a new one via `checkout -b`). Untracked files are unaffected.
  Commit `4a6146c`.

## Testing

Full real (non-`--check`) end-to-end validation on `servyy-test.lxd` via the
actual deployment pipeline (`./servyy-test.sh --tags user.docker.repo,
user.docker.opencode`), including deliberately seeding orphan clones first
to prove removal, and cycling through several rounds as the git-crypt/
checkout issues above were found and fixed. Final run: clean recap, correct
branch/commit deployed, orphans removed, `dachrisch/`/`bumbleflies/` nested
repos untouched, `prune-sessions.py` runs clean, Ofelia labels present.

## Deployment

```
cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.opencode --limit codey.lehel.xyz < /dev/null
```

## Verification

```
ssh codey.lehel.xyz "docker exec opencode.web ls /root/dev"     # only dachrisch/, bumbleflies/
ssh codey.lehel.xyz "sudo du -sh /var/lib/docker/volumes/opencode_opencode_root/_data"  # 7.4G -> 4.2G
ssh codey.lehel.xyz "docker exec opencode.web python3 /scripts/prune-sessions.py"        # exit 0
ssh codey.lehel.xyz "df -h /"                                    # 67% -> 60% used
curl -I https://code.lehel.xyz/                                  # unchanged (401, auth-gated)
```

## Known Issues / Follow-up

1. **Vaultwarden SSH-key backup push failed on deploy** (not fixed today).
   `ansible/plays/roles/vaultwarden/tasks/push_items.yml:25-27` needs a real
   unlocked `bw` session; skipping the Vaultwarden prompt via `< /dev/null`
   is documented as safe for restic but isn't safe for this opencode-role
   handler whenever it rewrites SSH keys/env files. The keys themselves
   wrote to disk correctly — only the redundant Vaultwarden backup copy
   failed. `ansible/plays/roles/opencode/handlers/main.yml` triggers it.

2. **Neither the new `npm-cache-clean` job nor the pre-existing
   `prune-sessions` job is actually scheduled on codey** (not fixed today,
   more significant than it first appeared):
   - `ansible/plays/roles/opencode/handlers/main.yml`'s `restart opencode
     container` handler deliberately uses `docker compose restart` (not a
     recreate) — a prior fix to avoid a data-loss bug where recreating
     silently dropped compose-managed volumes/env/networks. A plain restart
     re-execs `startup.sh` (so script-level changes like the orphan cleanup
     take effect) but **cannot** apply container label changes from an
     updated compose file — so the new `npm-cache-clean` labels never
     reached the live container on this deploy.
   - More fundamentally: **no Ofelia scheduler container runs on codey at
     all.** `ansible/production` only sets `portainer: true` (which
     deploys Portainer + Ofelia) on `servy.lehel.xyz`; codey only has
     `portainer-agent: true`. Ofelia's Docker-label auto-discovery only
     sees containers on the same Docker daemon it's attached to — it can't
     reach across to codey's separate host/daemon. This means the
     `prune-sessions` job from `2026-09-04_opencode-session-prune-
     automation.md` (designed with codey's opencode instance in mind) has
     likely never actually run automatically in production; `docker exec
     opencode.web python3 /scripts/prune-sessions.py` works correctly when
     invoked manually (confirmed today), but nothing currently triggers it
     on a schedule on this host.
   - Needs a real fix: either deploy Ofelia to codey too, or switch to a
     host-local scheduler (e.g. a systemd timer running `docker exec`,
     matching the pattern already used for `docker_cleanup`/`kernel_cleanup`
     in the `system` role) — not attempted today, deferred pending a
     decision.
