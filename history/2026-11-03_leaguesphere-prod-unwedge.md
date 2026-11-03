# LeagueSphere prod unwedged: 5.2.0 → 5.8.12 plus the memory cap that never landed

**Date:** 2026-11-03
**Status:** ✅ **Deployed** to `servy.lehel.xyz` (no code change in this repo — the fix was the
standard `ls_app` deploy, run because the updater was wedged)
**Relates to:** `2026-09-26_watchtower-fork-swap.md`, `2026-09-27_watchtower-tag-fix.md`,
leaguesphere `38cbccda3` (prod app memory cap)

## Context

`portainer.watchtower-prod` had been emitting the same warning every two hours since
2026-10-30 10:59 — the first surviving log line of the current watchtower container:

```
level=warning msg="Unable to update container — proceeding to next"
  container=/leaguesphere.app error="Error response from daemon: No such image: leaguesphere/backend:latest"
```

No pull was attempted. The fork aborts before pulling when the container's image tag is gone, so
the container could never self-heal. State on the host at the time:

| | prod `leaguesphere.app` | Docker Hub `leaguesphere/backend:latest` |
|---|---|---|
| Version | **5.2.0** | **5.8.12** (`9fe2dada`, pushed 2026-11-02 22:03) |
| Image | `359e62b3` — dangling, built 2026-10-29 21:41 | — |
| Container | created 2026-10-29 22:33, never recreated | — |
| Local tags | `leaguesphere/backend:latest` **missing** (only `:staging` + `:demo`) | — |

`leaguesphere.www` kept updating normally (blue-green cutover logged 2026-11-03 01:00), so prod had
been serving a current frontend against a five-day-old backend. Staging and demo on the same host
already ran 5.8.12, i.e. the image itself is fine.

Two compounding facts:

1. **Why the tag vanished** (inference, but well supported): a blue-green swap after the Oct 29
   deploy pulled `latest` (moving the tag), the green container never went healthy, and the fork's
   rollback deleted the pulled image *by ID* — which removes its tags too. No newer backend image
   is left anywhere on the host, the running container was never recreated, and the warning starts
   in watchtower's first session after its own Oct 30 redeploy (older logs were lost with it;
   `journalctl -u docker` is not readable as `cda`). Same failure signature as the ongoing
   `shared.mongo` flapping.
2. **The Oct 30 memory fix never landed.** The container still ran `mem_limit: 1g` with gunicorn
   `-w 6`; the repo had moved to `1.5g` / `-w 4 --max-requests 500` (`38cbccda3`). Watchtower
   recreates a container from its *existing* config, so only a `compose up` can apply it. The
   evidence matched the comment that motivated the cap: 658 MiB of 1 GiB used, cgroup
   `memory.events` `max=16125`, `oom_kill=2`, `sock_throttled=23080`.

The site itself was healthy throughout (`leaguesphere_maintenance_blocking_games=0`,
`leaguesphere_health_probe_success=1`, 14457× 200 / 0× 5xx in 24 h) — this was a stuck release, not
an outage.

## Decision

Run the standard Ansible deploy for the prod role only, so the same run restores the tag, applies the
memory cap and rolls the release forward through the normal migration path
(`RUN_MIGRATIONS=true` for prod):

```
cd ansible && ansible-playbook servyy.yml -i production --limit servy.lehel.xyz \
  --tags "ls.app.prod" -e root_user=cda -e vw_master_password=unused
```

`-e root_user=cda` because root SSH to servy is denied and `cda` has passwordless sudo;
`-e vw_master_password=…` because the always-tagged Vaultwarden play would otherwise block on an
interactive `pause` (`~/.ssh/vw.key` does not exist in this container) and nothing in `ls_app` uses
it.

Rejected: `docker pull leaguesphere/backend:latest` alone (zero downtime via watchtower, but keeps
the 1 g / 6-worker config and hands the release time to watchtower's 2 h poll).

## Consequences

### Positive
- ✅ Prod backend 5.2.0 → **5.8.12**, `leaguesphere/backend:latest` restored (`9fe2dada`), i.e. the
  updater can update again — the every-2 h warning is gone by construction.
- ✅ Memory cap landed: `mem_limit 1.5g`, `-w 4 --max-requests 500 --max-requests-jitter 100`;
  container settled at **477 MiB / 1.465 GiB** with no reclaim pressure.
- ✅ Frontend/backend version skew removed.
- ✅ Migrations applied by the container itself (`RUN_MIGRATIONS=true`); startup clean, 0
  tracebacks/errors, health `healthy`, site `301` → `/health/ 200`.
- ✅ No manual change on the host: the jail checkout was git-pulled and the stack recreated by the
  role (`pull: always`, `recreate: auto`).

### Negative / Tradeoffs
- ⚠️ ~20 s app restart (compose recreate, not blue-green) — run while
  `leaguesphere_maintenance_blocking_games == 0`; it was 0 at the time.
- ⚠️ The wedge itself is still possible: floating `latest` + a rollback that deletes the pulled
  image leaves watchtower stuck on a container whose tag no longer exists.

### Implementation Details

- No files changed in this repo; the deploy pulled `dachrisch/leaguesphere@master` into
  `/var/jail/home/leaguesphere/container/deployed` and rendered `docker.env` / `ls.env`.
- Verification:
  `docker exec leaguesphere.app python -c 'import league_manager; print(league_manager.__version__)'`
  → `5.8.12`; `docker inspect` → `mem=1572864000`, `-w 4 … --max-requests 500`;
  `docker ps` status `Up (healthy)`; `docker stats` 477 MiB / 1.465 GiB.

### Key Learnings
1. **A failed blue-green swap can permanently wedge the updater.** The rollback removed the pulled
   image (tags included), after which the fork never pulls again for that container — it only warns.
   A watchtower that stops updating is therefore silent unless the log line is alerted on.
2. **The prod DB was already at the 5.8.12 schema while 5.2.0 served traffic** — the startup log
   says “No migrations to apply”. So the failed Oct 30 green container *did* migrate before it was
   rolled back, and prod ran five days on a schema ahead of its code. Anything relying on that
   mismatch (or on a rollback to run migrations down) would have been wrong.
3. **`dig` lookup needs `dnspython`** — `ls_app/templates/docker.env.j2` uses `lookup('dig', …)`,
   which fails inside the opencode container unless `python3 -m pip install --break-system-packages
   dnspython` has been run; the play aborted on the env task before touching containers.
4. **`ansible/servyy.sh` needs zsh**, which the container lacks — call `ansible-playbook` directly.

### Known Issues & Limitations
- `shared.mongo` still fails watchtower's health gate every 2 h and rolls back to the July image
  (`e0ce8c35`), i.e. mongo restarts twice an hour for ~30 s. Separate investigation.
- Nothing alerts on `No such image` / update failures in the watchtower logs, nor on the running
  LeagueSphere version drifting from Docker Hub — which is why this went unnoticed for five days.
- This container's `servyy-container` checkout was 39 commits behind and carries a git-crypt file
  (`ansible/plays/roles/user/defaults/main.yaml`, deleted upstream in `0ffe96a`) that checks out as
  0 bytes, so `git pull --ff-only` aborts. The `ls_app` role is identical to master, so the deploy
  was still run from it.

## Related Decisions
- `2026-09-26_watchtower-fork-swap.md` — health-gated updates; the rollback that wedged this.
- `2026-09-27_watchtower-tag-fix.md` — Hub tag naming for the fork.
- leaguesphere `38cbccda3` — the prod app memory cap this deploy finally applied.

## Alternatives Considered

### Alt A: `docker pull leaguesphere/backend:latest` only
Pros: zero downtime, unblocks watchtower within 2 h.
Cons: keeps the 1 g / 6-worker config, and puts the release inside a game-day-agnostic 2 h window.
**Rejected** (used as the rollback path if the deploy had gone wrong).

### Alt B: manual `docker compose pull && up -d` in the jail
Pros: one command, no Ansible.
Cons: manual change on production, bypasses the repo, exactly what the deploy roles exist for.
**Rejected**
