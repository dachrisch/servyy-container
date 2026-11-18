# ADR: stop the deploy checkout rewriting every tracked file on every run

**Date:** 2026-11-18
**Status:** Accepted
**Relates to:** [`2026-11-18_monitor-render-out-of-checkout.md`](2026-11-18_monitor-render-out-of-checkout.md) (found this while making the monitor deploy idempotent, and reported the restart-window dashboard loss it causes), [`2026-10-27_checkout-permissions-safety-net.md`](2026-10-27_checkout-permissions-safety-net.md) (the `chmod a+rX` safety net this keeps), [`2026-10-22_hoefer-permissions-outage.md`](2026-10-22_hoefer-permissions-outage.md) (why that net exists)

## Context

Every Ansible deploy rewrote **every tracked file** in the deploy checkout
(`/home/cda/servyy-container`, and the same file drives `~/.zprezto`). Nothing
was wrong with the content — the tree was clean against git — but each run left
the checkout stat-dirty, so the next run re-checked it out.

The loop:

1. `git reset --hard` in `roles/user/tasks/includes/repository.yml` writes the
   tree under umask 007 → files `0660`, dirs `0770`.
2. The same file then chowns the whole tree (`find … -exec chown {} +`) and
   re-applies `chmod a+rX` on the container-consumed paths. **POSIX updates
   ctime on every `chmod`/`chown` call, not only on an effective change** —
   measured on `monitor/loki.yml`: `chmod a+rX` with an already-correct mode
   moved ctime from `12:01:48` to `12:16:27`, and a no-op `chown` moved it
   again.
3. Git's index stores the ctime it saw when it wrote each file. With the ctime
   bumped 20 s after the checkout, every entry looks "possibly changed", so the
   next `git reset --hard` rewrites the whole tree — back to step 1.

Symptoms, all measured before the fix:

| symptom | measurement |
|---|---|
| every deploy rewrites the tree | `monitor/promtail.yml` mtime == the last checkout, every run |
| repo-sync-only deploys always "change" something | `--tags user.docker.repo` → `changed=1` on every run, always the `chmod a+rX` task |
| index vs file ctime | index `ctime 1794999427` (11:57:07) vs file `ctime 11:57:27` |
| a `0660` window on every deploy | files are `0660` from the moment the checkout writes them until the `chmod` runs |
| a container restarted in that window | Grafana scanned provisioning at `11:51:26` after a checkout rewrote the dashboards at `11:51:21` → `permission denied` on all 9 dashboard JSONs for that boot (non-fatal, self-healed on the next restart) |

The `chmod a+rX` safety net (added after the achim-hoefer 403s and grafana
"permission denied" outages) was therefore fighting a checkout that it had
itself caused to rewrite: it did real work every run, which is exactly why the
problem never went away.

## Decision

Break the ctime → stat-cache → rewrite cycle at both ends, without changing what
the deploy guarantees:

1. **Chown only what is wrong.** One `find` over the tree with the predicate
   `\( ! -user <create_user> -o ! -group docker \)` instead of two full-tree
   `-exec chown {} +` passes. In steady state nothing is chowned, so nothing is
   ctime-bumped by ownership.
2. **Re-record the stat info at the very end of the file** —
   `git update-index --refresh` after both chmods (the world-readable one and
   the `go-w` one). That writes the post-chmod ctimes into the index, so the
   *next* checkout reads a clean tree and writes nothing.

`git update-index --refresh` cannot hide a real modification: for an entry whose
stat differs it re-hashes the content, keeps the entry dirty and prints "needs
update" — which is precisely what the next `reset --hard` is supposed to
discard. `failed_when: false` is there because rc=1 only means "some entry needs
update".

The chmods themselves are left alone on purpose: they are the safety net that
makes the checkout physically unable to leave a container-unreadable tree, and
with the index no longer going stale they are cheap no-ops instead of a trigger.

## Consequences

### Positive

- ✅ **Three consecutive repo-sync deploys: `changed=1` → `changed=0` →
  `changed=0`**; the tree is written once per actual change, not once per run.
- ✅ No more `0660` window on every deploy — the only window left is a genuine
  commit landing, which is the unavoidable one.
- ✅ Restarting a container after a deploy no longer races a full-tree rewrite:
  Grafana restarted right after a repo sync → `0` permission errors, `9/9`
  dashboards.
- ✅ Less I/O on a host that has been under disk pressure: one conditional
  `find` instead of two full `chown` passes plus a full-tree rewrite per deploy.
- ✅ Analogous directory (`~/.zprezto`, which shares this task file) gets the
  same treatment: the `go-w` narrowing no longer re-triggers a checkout.

### Negative / Tradeoffs

- ⚠️ One extra git command per deploy (a stat pass over the tree, no content
  hashing in the common case).
- ⚠️ The chown is now conditional, so if a *future* task creates a file with the
  wrong owner **and** the find predicate misses a case (e.g. an entry the deploy
  user cannot stat), ownership would not be blanket-corrected any more. The
  predicate covers both user and group on every entry, which is what the two
  `-type` passes covered.
- ⚠️ `git update-index --refresh` can print `needs update` lines into deploy
  output when a task has genuinely modified a tracked file (the opencode role
  does this by design). Informative, not an error.

### Implementation Details

**Files modified:**
- `ansible/plays/roles/user/tasks/includes/repository.yml` — conditional chown; new trailing `git update-index --refresh` task
- `history/2026-11-18_checkout-ctime-churn.md` — NEW (this file)
- `history/2026-11-18_monitor-render-out-of-checkout.md` — its "known issue" cross-references this fix

**Commits:**
- `89afaef9` fix(user): stop the checkout rewriting every tracked file on every deploy

**Testing & Verification (production, servy.lehel.xyz):**

| step | result |
|---|---|
| `--tags user.docker.repo` (after the fix landed) | exit 0, `changed=1` (only the new commit's files) — the `chmod a+rX` task reported **no** change |
| same again, nothing new to pull | exit 0, **`changed=0`** |
| `--tags user.docker.repo,user.docker.monitor` | exit 0, **`changed=0`** |
| files newer than 3 min after a repo-only run | 5 (the files of the latest commit) instead of the whole tree |
| index vs file ctime after a run | identical (`1795000818:576437451`) |
| `monitor/promtail.yml` | mtime still the previous checkout (`12:01:27`), mode still `0664` — never rewritten |
| `git status --porcelain` (tracked) | empty |
| `docker compose restart grafana` right after a repo sync | `0` permission errors, `9/9` dashboards, container healthy |

**Key Learnings:**

1. **ctime is the hidden coupling** between an idempotent-checkout model (git
   stat cache) and file-mode/permission enforcement: `chmod`/`chown` are
   "no-op" at the mode level but never at the inode level. Any deploy that both
   rewrites a tree and then normalises its modes needs to refresh the index
   afterwards, or it will rewrite the tree forever.
2. **A safety net that re-applies modes on every run can be the thing that makes
   the run non-idempotent** — and it silently hides the real cause, because the
   mode outcome is correct every time. `changed=1` on a no-op deploy was the
   only visible symptom.
3. **`git ls-files --debug` is the oracle** for "is this tree clean or just
   content-clean": comparing the stored ctime against `stat` identified the
   mechanism in one command.
4. Conditional mutations (`find … ! -user …`) are almost always the right shape
   for Ansible tasks that must run on every deploy but change nothing.

**Known Issues & Limitations:**

- Any future task that touches the tree *after* this refresh task re-opens the
  window for that run. Keep tree-touching tasks above it in the file.
- Genuinely modified tracked files (the opencode role writes its compose file
  directly) are still discarded by the next `reset --hard`; that is the existing
  contract and unchanged here.

## Alternatives Considered

### Alt A: make the chmod conditional as well
Pros: removes the remaining ctime bumps.
Cons: `a+rX` semantics are awkward to express as a `find` predicate (files vs
dirs vs executables), and the chmod must stay unconditional to remain the safety
net that the achim-hoefer/grafana incidents demand. The index refresh makes the
bump harmless instead.
**Rejected** (kept the chmod as-is).

### Alt B: run the checkout with umask 002
Pros: files land `0664`, dirs `0775` — no `chmod` needed at all, and the
git-crypt'd secrets would still be group-only.
Cons: touches every service's assumption about modes, needs regeneration of the
whole existing tree, and does nothing about the chown ctime bump.
**Rejected** for scope; revisit if mode handling ever needs rework.

### Alt C: drop the blanket chown entirely
Pros: no full-tree pass at all.
Cons: the chown is what repairs root-owned files written by earlier tasks; the
conditional form keeps that capability for free.
**Rejected.**

### Alt D: `git status --porcelain` instead of `git update-index --refresh`
Pros: silent output.
Cons: does more work (it hashes on stat mismatch) and hides the "needs update"
signal that is useful in deploy logs.
**Rejected.**

## Related Decisions

- [`2026-11-18_monitor-render-out-of-checkout.md`](2026-11-18_monitor-render-out-of-checkout.md) — where the churn was isolated and the restart-window race observed
- `CLAUDE.md` → "Never `git pull` the deploy checkout on the server"
