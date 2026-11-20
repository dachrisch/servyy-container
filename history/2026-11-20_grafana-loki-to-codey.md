# Grafana + Loki moved from servy to codey (one project, two compose profiles)

**Date:** 2026-11-20
**Plan:** [`docs/plans/2026-11-20_grafana-to-codey.md`](../docs/plans/2026-11-20_grafana-to-codey.md)
**Relates to:** [`2026-11-18_monitor-render-out-of-checkout.md`](2026-11-18_monitor-render-out-of-checkout.md)
(the render-into-`rendered/` pattern this change extends),
[`2026-09-…` Loki off Traefik](../monitor/docker-compose.yml) (the exposure decision
this change partially reverses — behind auth this time)

## Context

servy (4 vCPU / 7.7 GB, docker disk 71 % full, swap in use) carried the whole
observability stack; codey (Oracle A1, 2 vCPU / 12 GB) idled. Moving Grafana +
Loki frees ~560 MB RAM, ~0.11 cores and ~4.5 GB of servy's docker disk, and makes
alerting survive a servy outage — the alerting engine no longer lives on the host
it watches.

The plan's boundary is deliberate: **Prometheus, pushgateway (+bridge),
node-exporter, cadvisor and promtail stay on servy**, because every one of them
reads that machine (`/proc`, `/sys`, the Docker socket, `/var/log`) and every
host probe pushes to `localhost:9091`.

**User decision:** Loki and Grafana start **fresh** on codey. No data migration;
servy's `monitor_grafana_data` and `monitor_loki_data` volumes are deleted after
the cutover. Dashboards, alert rules, contact points and datasources are
file-provisioned, so they come along; `roles/monitor_grafana_auth` re-asserts the
admin password on the new `grafana.db`.

## What changed

### One compose project, two profiles

`monitor/docker-compose.yml` splits into compose profiles instead of becoming two
services, so container names (`monitor.grafana`, `monitor.loki`, …) and the
existing roles stay unchanged:

| profile | services | host |
|---|---|---|
| `ui` | grafana, loki | codey |
| `collect` | prometheus, pushgateway, pushgateway-bridge, node-exporter, cadvisor, promtail | servy |

- Per-host `monitor_profiles` (servy `[collect]`, codey `[ui]`, servyy-test
  `[collect, ui]`) is rendered into `monitor/.env` as `COMPOSE_PROFILES` **and**
  passed to `community.docker.docker_compose_v2` as `profiles`, so a hand-run
  `docker compose up -d` on the host selects the same half.
- The cross-profile `depends_on` entries (grafana→prometheus, promtail→loki) are
  gone; compose refuses a dependency on a service whose profile is inactive.
- `monitor_reload` runs only the half whose container exists
  (`monitor_reload_{prometheus,grafana}_enabled`), and its fingerprints now cover
  the new rendered files (`rendered/loki-target.json`, `rendered/loki-password`
  for Prometheus; `rendered/datasources.yml` for Grafana).
- `roles/monitor_grafana_auth` is gated on `ui`.
- The container-health probe is profile-aware: it reads each compose file's
  `profiles:` and emits only the services the host's `monitor_profiles` activates.
  Without that, servy reported grafana/loki down for ever (and codey reported the
  five collectors). `system_probe_push_enabled` additionally requires `collect`,
  because codey has no Pushgateway sink.
- Cleanup: `plays/tasks/monitor_ui_cleanup.yml`, gated on `'ui' not in
  monitor_profiles`, removes `monitor.grafana` and `monitor.loki` and their two
  volumes on servy. Compose never removes a profile-disabled service, and its
  `restart: unless-stopped` would keep it alive. The task names the four objects
  explicitly — no `down --remove-orphans`, which would take `prometheus_data`
  (the alerting history) with it.

### The two new network paths (the only widened surface)

| route | served by | callers | auth |
|---|---|---|---|
| `loki.lehel.xyz` | codey → `monitor.loki:3100` | servy's promtail (push), servy's Prometheus (`/metrics`), fail2ban on servy **and codey** | user `promtail` |
| `prometheus.lehel.xyz` | servy → `monitor.prometheus:9090` | codey's Grafana datasource | user `grafana` |

Loki left Traefik in 2026-09 precisely because it had no auth; it returns only
behind **basicAuth + ipAllowList**, on `websecure` only, with no `web` router.
Middleware order is auth → allow, so an unauthenticated request answers 401 and
an authenticated one from a third address answers 403.

- Credentials are **literal** values in `plays/vars/secrets.yml`
  (`monitor_remote_auth.{loki,prometheus}_password`), deliberately not
  `lookup('password', 'vars/.…')` seeds — those exist only on the controller that
  first rendered them and would silently rotate on a fresh checkout (CLAUDE.md
  rule 6). The values are `[A-Za-z0-9]{16,}` so one literal is safe in an htpasswd
  line, a YAML scalar, a `password_file` and a shell assignment.
- `roles/monitor_remote_auth` hashes them into
  `traefik/monitor-{loki,prometheus}-auth.htpasswd` (APR1, salt derived from the
  secret, same technique as the dashboard auth), and
  `traefik/dynamic.yaml` defines the two `basicAuth.usersFile` middlewares.
- `ipAllowList` ranges are per host in `monitor/.env` (`MONITOR_*_ALLOW`) because
  `traefik/dynamic.yaml` is shared and servyy-test reaches itself from a private
  address. Codey is on the Loki list because its own `loki-blocklist` jail polls
  the same Loki — it runs on every host, and would otherwise start failing with a
  403 now that the route it already used (`monitor.lehel.xyz/loki`) is gone.

### Config files: secrets rendered out of the checkout

Following the 2026-11-18 rule, no committed file that a container reads holds a
credential or raw Jinja:

- **Grafana datasources** became a template: `monitor/provisioning/datasources/datasources.yml`
  is the Jinja source, Ansible renders `monitor/rendered/datasources.yml`, and
  compose mounts it over the tracked path. Prometheus is now
  `https://prometheus.lehel.xyz` + basicAuth; Loki stays `http://loki:3100`
  (same project on codey). Datasource uids `prometheus`/`loki` are unchanged —
  every alert rule names them. The deploy asserts the rendered file has no `{{`,
  a 16+ char `basicAuthPassword`, a `url:` and the `prometheus` uid.
- **promtail** pushes to `${LOKI_PUSH_URL}` (`-config.expand-env=true`) with
  `basic_auth.password_file: /etc/promtail/loki-password`; the password is
  rendered to `monitor/rendered/loki-password` and mounted read-only. Promtail
  now also joins the external `proxy` network — `backend` is `internal: true` and
  has no route to codey.
- **Prometheus**' `loki` job uses `file_sd_configs` over
  `rendered/loki-target.json` plus `basic_auth.password_file`. The target file is
  strict JSON (`loki-target.json.j2` documents why: the `.json` extension selects
  Prometheus' JSON parser, which rejects comments) and carries the per-environment
  scheme as a `loki_scheme` label that one `relabel_configs` rule copies onto
  `__scheme__` (file_sd labels cannot set `__scheme__` themselves — Prometheus
  overwrites it from the scrape config first). Production scrapes
  `https://loki.lehel.xyz:443`; servyy-test its local Traefik over `http`.
- **fail2ban**'s Loki helper no longer tries the docker-network shortcut or the
  dead `monitor.lehel.xyz/loki` path: it uses `monitor_loki_url` plus
  `curl -u`, and the rendered script is installed `0700 root` instead of `0755`
  because it now carries the password.

## Deviations from the plan (all deliberate, all reported)

1. **Deploy tags include `user.docker.traefik`.** The plan's rollout commands
   used `user.docker.repo,user.docker.monitor`. Both new routes need the host's
   Traefik to have the new `dynamic.yaml` and the two htpasswd mounts, which only
   a traefik deploy applies (the compose spec changes, so the container is
   recreated and the new inode is what Traefik reads).
2. **Codey is on the Loki allowlist.** The plan listed servy only; codey's own
   fast2ban jail polls the same Loki.
3. **`system_probe_push_enabled` is false on servyy-test.** The probe is generated
   from the production `docker.services` list, so enabling it on test would report
   ~40 containers that must not exist there as down — and test now runs Grafana,
   which evaluates the same alert rules with a live mail contact point.
4. **Grafana's `GF_SERVER_ROOT_URL` follows the entrypoint** (`MONITOR_PUBLIC_URL`):
   https in production, http on servyy-test, which has no TLS listener for that
   name.
5. **The URL/scheme knobs live in `vars/default.yml`** with
   ansible/testing overrides, rather than hard-coded `lehel.xyz` names.
6. **`--worktree` was not used** (the branch already existed in this checkout, by
   the user's instruction).

## Verification

Static (all green before any deploy):

- `ansible-playbook servyy.yml --syntax-check -i production` / `-i testing`.
- `ansible-lint` on the changed plays/roles: 0 failures, 0 warnings (130 files).
- `.github/scripts/validate-git-crypt.sh`: compose files still plaintext,
  `secrets.yml` still git-crypt-tracked, blobs round-trip.
- `check_published_ports.py`: 28 compose files, no new `0.0.0.0` publish.
- `architecture/render.py --verify`: 30 services, 49 edges, 4 tiers agree.
- Local render of the profile-aware probe: `monitor.prometheus` and
  `monitor.always` emitted, `monitor.grafana` absent for `monitor_profiles:
  [collect]`.
- Local render of `monitor/.env`: `COMPOSE_PROFILES=ui`,
  `LOKI_PUSH_URL=https://loki.lehel.xyz/loki/api/v1/push`, allowlists and
  entrypoint/TLS/resolver as configured; the test override renders
  `http://monitor.servyy-test.lxd` and `web`.
- Local render of the datasource and target: valid YAML/JSON, uids preserved, no
  `{{`.
- `roles/monitor_remote_auth`: both APR1 entries re-verified against their
  plaintext with `openssl passwd -apr1 -salt …`.

Environment verification (servyy-test, then production) is recorded below once
the rollout runs: container placement, Grafana datasource health, alert-rule
count and health, Loki freshness, `up{job="loki"}`, the fail2ban helper, the
container-health probe, the 401/403 negative tests, a contact-point test
notification, and the disk/swap reclaim on servy.
