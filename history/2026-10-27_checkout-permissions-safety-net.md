# Checkout permissions safety net (world-readable paths re-applied after every repo sync)

**Date:** 2026-10-27
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz`
**Related:** `history/2026-10-22_hoefer-permissions-outage.md` (same failure, first occurrence), `history/2026-10-27_servy-disk-reclaim-and-job-search-retirement.md`

## Context

The deploy checkout runs under **umask 007**, so `git reset --hard` restores
tracked files as `0660` and directories as `0770` — readable by `cda` and the
`docker` group only. That is deliberate: the git-crypt'd secret files depend on
group-only read.

Container processes that run as a **non-root uid** and read bind-mounted
checkout content therefore cannot read it. The 2026-10-22 incident added
`world_readable_paths` to the `docker_service` role so a service could declare
what must be opened up — but the chmod only ran **inside that service's own
role**.

That left a trap: a `--tags user.docker.repo` run performs the checkout and
nothing else. It rewrites every mode to `0660` and no role re-opens anything.

This happened three times in one evening:

| When | Service | Symptom |
|---|---|---|
| 2026-10-22 | achim-hoefer | nginx 403 → healthcheck fails → Traefik withdraws routers → 404 |
| 2026-10-27 22:42 (my `--tags user.docker.repo`) | achim-hoefer again | same 404 |
| 2026-10-27 22:32 | monitor | `grafana` exited "failure to parse file … permission denied"; `prometheus` exited "Error loading config: open /etc/prometheus/prometheus.yml: permission denied" |

The monitor case was worst: both containers **dropped out of the compose
project entirely**, so the Grafana UI and all metric ingestion vanished with no
obvious signal. Loki was still running only because its container predated the
mode change — it would have died on its next restart. `traefik/error-pages.html`
and `moodle/config.php` were in the same latent state.

## Decision

Make the declarations a single source of truth and apply them **twice**:

1. `plays/vars/default.yml` → `world_readable_paths_by_service`, each entry
   annotated with the uid that needs it (traefik/10001, achim-hoefer/101,
   moodle/33, monitor/472+65534+10001).
2. The four `docker_service` role invocations in `plays/user.yml` read that map
   (`world_readable_paths: "{{ world_readable_paths_by_service[service_dir] | default([]) }}"`)
   instead of carrying their own copy — no second list to drift.
3. `plays/roles/user/tasks/includes/repository.yml` re-applies the modes
   immediately after the ownership pass: stat each declared path, then a single
   `chmod -cR a+rX` over the ones that exist.

`a+rX` (not `a+r`) so directories gain traversal without making regular files
executable, and `-c` so only real mode changes are reported (re-runs stay green).
The task cannot fail on a host where a service is not deployed.

## Consequences

### Positive

- ✅ A repo-sync-only run can no longer leave services 403/refusing to start
- ✅ One declaration per service; the role and the sync cannot disagree
- ✅ The latent `error-pages.html` / `config.php` breakage was fixed in passing
- ✅ Verified by running the exact command that broke things
  (`--tags user.docker.repo`): modes went `0660 → 0664` for all declared paths
  in the same run, `failed=0`, achim-hoefer healthy, all three hostnames 200

### Negative / Tradeoffs

- ⚠️ The sync now chmods every declared path on **every** repo sync, including
  hosts where that service is not enabled (harmless, but it is work the host
  would not otherwise do)
- ⚠️ The umask itself is unchanged — deliberately. Running the checkout under
  `022` would fix this globally but expose the git-crypt'd secrets.

### Implementation Details

- `ansible/plays/vars/default.yml` (NEW map)
- `ansible/plays/user.yml` (4 role invocations)
- `ansible/plays/roles/user/tasks/includes/repository.yml` (NEW post-checkout pass)
- Commits: `6714de0`, `5980069`

**First attempt failed:** the chmod was written as a loop with
`changed_when: item.stdout | length > 0`. Inside a loop, `item` is the *loop*
item (the stat result), not the command result, so every item errored with
`'dict object' has no attribute 'stdout'` — while the chmods had in fact
applied. Collecting the paths first and running one `chmod -cR` keeps the
result addressable.

### Verification

```
stat -c '%a %n' traefik/error-pages.html moodle/config.php achim-hoefer/serve/index.html \
                monitor/prometheus.yml monitor/loki.yml monitor/provisioning/alerting/alert-rules.yml
664 traefik/error-pages.html
644 moodle/config.php          # already world-readable, unchanged
664 achim-hoefer/serve/index.html
664 monitor/prometheus.yml
664 monitor/loki.yml
664 monitor/provisioning/alerting/alert-rules.yml

https://höfer-architekten.de/      200
https://www.höfer-architekten.de/  200
https://achim-hoefer.lehel.xyz/    200
monitor.grafana / monitor.prometheus   Up (healthy)
grafana: 9 dashboards, 37 alert rules provisioned, 0 provisioning errors
```

### Key Learnings

1. **"The fix is in place" is not the same as "the fix runs where it matters."**
   `world_readable_paths` existed for 5 days and the outage still happened,
   because the only code path that applied it was the service's own role.
2. **Partial deploys are the risky ones.** A full `servyy.sh` runs everything
   and self-heals; a single-tag run does not. Any invariant established by one
   role must be re-established by the task that breaks it.
3. **Check-mode hid nothing but the review missed it**: the `--check` run I did
   before the first real deploy showed `changed` for the render tasks only, not
   for the permission tasks — the signal was there.

### Known Issues / Open Findings

- A container that is **Running but unhealthy** (Traefik withdrawn its routers,
  the 2026-10-22 signature) is invisible to the `container_not_running` alert,
  which only reads `.State.Running`. That outage class is caught only by the
  external HTTP monitor.
- ~~`moodle/docker-compose.yml` names its compose service **`app`**~~ — **RESOLVED 2026-10-27**
  (`e807aff`): the service is now `moodle` (container `moodle.moodle`), so the alias `app` is
  LeagueSphere's alone again. Named `moodle` rather than `web` because `web` is already a shared
  alias (`bnb-office.web`, `dontforget.web`) — same bug class. Verified after a forced recreate:
  `app` → `172.25.0.6`, leaguesphere.app 200. See
  [2026-10-27_moodle-proxy-alias-outage.md](2026-10-27_moodle-proxy-alias-outage.md).
  Original finding, kept for the record: the alias `app` collided with leaguesphere's backend alias;
  leaguesphere's frontend re-resolves `app:8000` every 5 s and intermittently proxied to moodle → 502
  → unhealthy → routers withdrawn → 404 on leaguesphere.app (2026-10-27, ~10 min). Mitigated at the
  time by detaching `moodle.app` from `proxy`.

## Alternatives Considered

### Alt A: run the checkout under umask 022
Pros: fixes the class globally, no declarations
Cons: exposes the git-crypt'd secrets to world read. **Rejected** (explicitly rejected in the 2026-10-22 entry too).

### Alt B: hardcode the paths in the repo-sync task
Pros: smaller diff, one file
Cons: a second list that drifts from what each role opens. **Rejected** — the drift is what the central map exists to prevent.

### Alt C: chmod the whole checkout a+rX
Pros: cannot miss a service
Cons: world-readable secrets, world-readable `.env` files. **Rejected**.

### Alt D: make `--tags user.docker.repo` fail loudly unless paired
Pros: forces the operator to think
Cons: breaks the legitimate "just refresh the checkout" operation and does not fix the underlying ordering problem. **Rejected**.
