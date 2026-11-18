# ADR: render the monitor contact points out of the deploy checkout

**Date:** 2026-11-18
**Status:** Accepted
**Relates to:** [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md) (the incident this closes; it explicitly deferred this fix), [`2026-10-31_ls-maintenance-probe-alert-noise.md`](2026-10-31_ls-maintenance-probe-alert-noise.md) (the "`user.docker.repo` and `user.docker.monitor` must travel together" rule this removes), [`2026-11-18_db-tier-wp0-version-fence.md`](2026-11-18_db-tier-wp0-version-fence.md) (where the churn was first written down as pre-existing)

## Context

`--tags user.docker.monitor` was never idempotent. Every run re-rendered three
files into the deploy checkout and reported them changed:

- `monitor/promtail.yml` (`{{ monitor.loki_tenant }}`)
- `monitor/provisioning/datasources/datasources.yml` (`{{ monitor.loki_tenant }}`)
- `monitor/provisioning/alerting/contact-points.yml` (`{{ monitor_admin_email }}`)

Two separate causes had been conflated in the report ("changed=4, Grafana/Loki/
Prometheus restarted"), and separating them was most of the work.

### Cause 1 — the render target is a git-tracked path (systemic)

`docker.remote_dir` (`/home/cda/servyy-container`) is a **clone of this repo**,
and all three files are tracked. `roles/user/tasks/includes/repository.yml`
therefore fights the render on every deploy:

- `git reset --hard` (line 65, "Discard local working-tree modifications")
- `git reset --hard origin/master` + checkout inside the `git` module (line 73)

both restore the raw Jinja and the checkout's umask-007 modes. A render written
over a tracked path can never be "already correct" on the next run, and any run
that carries `user.docker.repo` **but not** `user.docker.monitor` (the
`--tags user.docker.repo,<service>` pattern used by every narrow deploy) reverts
the files and leaves them raw.

Measured on `servy.lehel.xyz` before the fix:

| observation | value |
|---|---|
| `monitor/promtail.yml` on the host | 5116 bytes, `0660`, md5 `01abd42a…` **== controller master** (raw Jinja) |
| `git status --short` / `git diff` | clean — the checkout had *reset* them, not modified them |
| reflog | `10:52:00 reset→origin/master`, containers created `10:52:53-55`, `11:07:00 "reset: moving to HEAD"` (repository.yml), `11:07:05 reset→origin/master` |
| result | the 10:52 deploy rendered; an 11:07 repo-sync-only run un-rendered it, 15 minutes later, and nothing re-rendered |

That is not only churn — it is a live outage hazard, re-verified in throwaway
containers (no production impact) against the files that were on disk:

```
docker run --rm -v <on-disk provisioning>:/etc/grafana/provisioning grafana/grafana:latest
  → EXIT=1 "Datasource provisioning error: yaml: unmarshal errors:
     line 23: cannot unmarshal !!map into string"      (identical to 2026-10-30)

docker run --rm grafana/promtail:latest -config.file=<on-disk promtail.yml> -dry-run
  → EXIT=1 "Unable to parse config … line 11: cannot unmarshal !!map into string"
```

Both were only masked by the containers holding the last *rendered* config in
memory: promtail had been up 4 days, and Grafana/Loki/Prometheus had been
recreated at 10:52 while the files were still rendered. Any restart or reboot
before the next monitor deploy would have taken monitoring down.

### Cause 2 — the "restart" was not the templates (one-off)

Compose does **not** react to bind-mounted content. Measured with the same
version the host runs (2.40.3+ds1), in a throwaway project:

| mutation | `docker compose config --hash` | `up -d --dry-run` |
|---|---|---|
| baseline | `cf4965…` | Running |
| edit a bind-mounted file | unchanged | Running |
| `chmod` a bind-mounted file | unchanged | Running |
| add/edit files inside a bind-mounted **directory** | unchanged | Running |

Confirmed against the real project: `docker compose up -d --dry-run` in
`monitor/` reported all 8 services `Running` while the three files on disk were
raw Jinja.

The recreation that accompanied the churn was a **one-time config catch-up**:
`grafana 512m`, `loki 512m` and `prometheus 768m` landed on 2026-10-29 18:47/19:05,
and 10:52 today was evidently the first `compose up` for the monitor project
since. Exactly those three services have a `mem_limit`; promtail, cadvisor,
pushgateway, pushgateway-bridge and node-exporter have none and were untouched.
It does not recur while the compose file is stable.

## Decision

Stop rendering anything over a file the containers read from the checkout, and
split the two kinds of value by secrecy:

1. **Loki tenant → committed inline.** `monitor.loki_tenant` is documented as
   public (`plays/vars/default.yml`) and recoverable from Loki's chunk directory
   names, so `monitor/promtail.yml` and
   `monitor/provisioning/datasources/datasources.yml` now carry
   `servyy-logs-k8x9m2p4q7` as plaintext and are no longer rendered at all.
2. **Admin address → rendered out of tree.** `contact-points.yml` keeps its
   Jinja source; Ansible renders it into `monitor/rendered/contact-points.yml`
   (untracked, gitignored), and `monitor/docker-compose.yml` bind-mounts that
   single file over `/etc/grafana/provisioning/alerting/contact-points.yml`. The
   directory mount `./provisioning` stays for everything else (dashboards,
   `alert-rules.yml`, `notification-policies.yml`, `datasources.yml`).
3. **Fail loudly, not at restart time.** After the render, `slurp` + `assert`
   require a real `addresses: …@…` and reject any unresolved `{{\s*[a-z_]+`
   placeholder. Grafana 13 treats a provisioning error as fatal, so this turns a
   silent no-op into a failed deploy.
4. `world_readable_paths_by_service.monitor` gains `promtail.yml`: it is mounted
   directly now and no longer gets the render task's `0644`, so it depends on the
   central list like every other container-consumed checkout file.

The pattern (untracked render target next to the compose file) is the one already
used for `.env` / `grafana.env`, so no new convention was introduced.

## Consequences

### Positive

- ✅ **Idempotent.** Second consecutive run: `changed=0` (was a guaranteed 3).
- ✅ The checkout is now clean against git after a monitor deploy — no more
  "three files modified" state that made `git pull` on the server dangerous.
- ✅ The 2026-10-30 trap cannot be re-triggered: no tracked file Grafana or
  promtail reads contains Jinja any more. A repo-sync-only run is harmless, so
  the "`user.docker.repo` and `user.docker.monitor` must travel together" rule is
  gone for promtail/datasources.
- ✅ A renamed/unset secret fails the deploy instead of provisioning a broken
  contact point.
- ✅ Dashboard/alert provisioning is unaffected: 9/9 dashboards load, both
  contact points report `provenance: file` with the resolved address.

### Negative / Tradeoffs

- ⚠️ The Loki tenant is now in three places (`plays/vars/default.yml`,
  `promtail.yml`, `datasources.yml`). `default.yml` still feeds
  `roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2`. A future
  tenant rotation must touch all three or the log pipeline silently splits per
  tenant; the comment on `monitor.loki_tenant` says so.
- ⚠️ `contact-points.yml` is shadowed, not removed: the raw Jinja copy still
  sits in `provisioning/alerting/` and is never read by Grafana. Anyone editing
  the tracked copy sees no effect until the deploy re-renders — same source of
  truth as before, just no longer load-bearing.
- ⚠️ `monitor/rendered/` lives inside the checkout (untracked). `git reset
  --hard` leaves it alone and nothing in the repo runs `git clean`, but if it is
  ever deleted by hand, the next `compose up` would bind-mount a directory where
  a file is expected and the next deploy's `template` fails on a directory dest.
  Both are loud; neither is silent.

### Implementation Details

**Files modified:**
- `monitor/promtail.yml` — tenant inline, plaintext note (was: broken Jinja on the host)
- `monitor/provisioning/datasources/datasources.yml` — tenant inline
- `monitor/docker-compose.yml` — grafana mount `./rendered/contact-points.yml` over the alerting path (`:ro`)
- `ansible/plays/user.yml` — render loop (3 tracked files) → dir + one templated file + read-back + assert
- `ansible/plays/vars/default.yml` — `promtail.yml` added to `world_readable_paths_by_service.monitor`; tenant-rotation note
- `.gitignore` — `monitor/rendered/`
- `CLAUDE.md` — "Never `git pull` the deploy checkout" rewritten for the new shape
- `history/2026-10-30_monitor-provisioning-render-trap.md` — superseded note
- `history/2026-11-18_monitor-render-out-of-checkout.md` — NEW (this file)

**Commits:**
- `48264d02` fix(monitor): render contact points outside the deploy checkout

**Testing & Verification (production, servy.lehel.xyz):**

| step | result |
|---|---|
| `./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.monitor` | exit 0, `changed=5` (clone, world-readable modes, render dir, render, `Deploy monitor`) |
| same command again | exit 0, **`changed=0`** |
| `--tags user.docker.repo` (the run that breaks prod today) | exit 0, `changed=1` (`chmod a+rX` only); `git status` has no modified tracked files afterwards |
| `docker compose up -d --dry-run` in `monitor/` | all 8 services `Running` |
| host files | `promtail.yml` + `datasources.yml` = plaintext tenant; `rendered/contact-points.yml` = 1397 bytes, `0644 cda:cda`, resolved address, Grafana subject templating intact |
| grafana mount | `rendered/contact-points.yml → /etc/grafana/provisioning/alerting/contact-points.yml` (read-only) |
| `docker compose restart grafana promtail` **after** a repo-sync-only run | grafana healthy, 0 provisioning errors, 9/9 dashboards, both contact points `provenance: file`; promtail re-seeked all tailed files and resumed writing to Loki |
| Loki, tenant `servyy-logs-k8x9m2p4q7` | `/loki/api/v1/labels` → `container, container_id, filename, job, program, service_name, stream` |

**Key Learnings:**

1. **A render target inside `docker.remote_dir` must be untracked.** `git reset
   --hard` runs on every deploy and on every `user.docker.repo` deploy, so a
   tracked render is non-idempotent forever *and* is one tag-filtered run away
   from reverting a container's config to invalid YAML. The 2026-10-30 entry said
   this; nothing enforced it, and it silently re-broke on 2026-11-18 11:07.
2. **Compose recreates on config/image change, never on mounted content.** The
   "monitor is recreated every time it is targeted" half of the report was a
   one-time `mem_limit` catch-up. Worth measuring before designing a fix around
   it: `config --hash` + `up --dry-run` are side-effect-free oracles.
3. **A single file bind mount over a directory bind mount is the cheap way out**
   of a "one file in this tree is secret" problem — it keeps the provisioning
   tree (dashboards, alert rules) managed by git while the secret-bearing file
   lives outside it.
4. **Grafana 13 provisioning is fatal for datasources but not for dashboards.**
   A dashboard file it cannot read is logged (`permission denied`) and skipped;
   a datasource file it cannot parse kills the process. Both failure modes were
   exercised during verification.
5. **Every deploy rewrites every tracked file.** `find … -exec chown` (line 148
   of `repository.yml`) bumps each file's ctime even when ownership does not
   change, which invalidates git's stat cache, so the next `git reset --hard`
   rewrites the whole tree at umask-007 modes. Restarting a container inside that
   window reads half-written `0660` files.

**Known Issues & Limitations:**

- Restarting Grafana *during or immediately after* a checkout can lose all 9
  dashboards for that boot: the checkout rewrites them `0660` and the
  world-readable `chmod` — and Grafana's one-shot provisioning scan — race. It is
  non-fatal (logged `permission denied`, no crash), does not affect datasources
  or contact points, and self-heals on the next restart once modes are restored.
  Observed once during verification (11:51:21Z checkout, 11:51:26Z Grafana scan);
  not addressed here.
- `datasources.yml` still lives under the directory mount, so its mode depends on
  the central `world_readable_paths` list; a future monitor config with a secret
  needs the `rendered/` treatment and not a new entry in that list.

## Alternatives Considered

### Alt A: `git update-index --skip-worktree` on the three files
Pros: one host-side command, nothing to change in the repo.
Cons: invisible state that survives clone/CI, silently swallows future template
edits, and is per-clone manual setup.
**Rejected.**

### Alt B: render in place, but fold the render into `repository.yml`
Pros: a repo-sync-only run could no longer leave raw Jinja.
Cons: fixes ordering only. The three tasks still churn every run, the checkout
still shows modified tracked files, and the idempotency claim stays false.
**Rejected** (it is the fallback if the mount approach had failed).

### Alt C: render all three files into `rendered/` and mount each
Pros: keeps the tenant centralized in `vars/default.yml`, uniform shape.
Cons: three mounts and a directory dependency for values that are public anyway;
`datasources.yml` is public in full, so it gains nothing.
**Rejected** in favour of committing the two public files.

### Alt D: compose `configs:` instead of a bind mount
Pros: compose fails fast if the source file is missing; no directory-creation
footgun.
Cons: needs long-syntax `target:` per file, and the repo uses bind mounts
everywhere else; the `template` + assert already covers the missing-file case.
**Rejected** for consistency.

## Related Decisions

- [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md) — the incident; its structural fix is this entry
- [`2026-10-09_monitor-contact-points-readable.md`](2026-10-09_monitor-contact-points-readable.md) — the `mode: '0644'` requirement this render keeps
- `CLAUDE.md` → "Never `git pull` the deploy checkout on the server"
