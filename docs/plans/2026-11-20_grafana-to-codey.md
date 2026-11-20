# Move Grafana + Loki from servy to codey

## Context
servy (4 vCPU / 7.7 GB / docker disk 49 GB at 71 %, 1.8 GB swap in use) is the busy
host; codey (Oracle A1 aarch64, 138.2.180.191, 2 vCPU / 12 GB / 73 GB free) idles at
load 0.3. Measured on 2026-11-20: moving **Grafana + Loki** frees about 560 MB RAM, about 0.11
cores (7-day average) and about 4.5 GB on servy's docker disk (loki_data 1.4 GB, grafana_data 0.6 GB,
grafana image 2 GB, loki image). It also means alerting keeps working when servy is down.

**Prometheus, pushgateway(+bridge), node-exporter, cadvisor and promtail stay on servy.**
They read servy's /proc, docker socket and logs, and every host probe pushes to
`localhost:9091`. Keeping Prometheus local means no exporter has to be exposed.

**Decision (user):** start Loki and Grafana **fresh** on codey. Do not copy or keep old data.
Delete servy's `monitor_grafana_data` + `monitor_loki_data` volumes after the cutover.
Dashboards, alert rules, contact points and datasources are file-provisioned, so they come
along. Admin password: `roles/monitor_grafana_auth` re-asserts it on the new grafana.db.

**Goal: everything works as before.** Same URL (https://monitor.lehel.xyz), same
dashboards, same alert rules firing on the same data. fail2ban's Loki blocklist keeps
working, the container-health probe stays green, and the same mail contact point is used.

## Design

### One service dir, two compose profiles
Keep `monitor/` as a single service, enabled on **both** hosts. Split it with compose
`profiles`. Then container names stay `monitor.grafana` / `monitor.loki`, and the existing
roles (`monitor_grafana_auth`, `monitor_reload`) work unchanged where they run.
- `profiles: [ui]` → grafana, loki
- `profiles: [collect]` → prometheus, pushgateway, pushgateway-bridge, node-exporter, cadvisor, promtail
- Per-host var `monitor_profiles` (servy: `collect`; codey: `ui`; servyy-test: `collect,ui`).
  Render it as `COMPOSE_PROFILES` into monitor's `.env`, or pass it to the compose module
  if `docker_service` uses `community.docker.docker_compose_v2` (check `roles/docker_service/tasks`).
- Remove the cross-profile `depends_on` (grafana→prometheus, promtail→loki). Otherwise compose fails.
- `ansible/production`: add `monitor: true` to codey's `services_enabled`, plus the `monitor_profiles` host vars.
- Gate `monitor_grafana_auth` + the Grafana half of `monitor_reload` on `'ui' in monitor_profiles`.
  Gate the Prometheus half on `'collect' in monitor_profiles`.
- **Container-health probe** (`roles/system_probe/templates/system_container_health.sh.j2`).
  It resolves names from each compose file at deploy time. Make it honour the host's
  profiles, so servy no longer expects monitor.grafana/loki and codey does not expect the
  collect containers. Check how the name list is generated and make it profile-aware.
  The probe runs on servy only, so Grafana/Loki liveness on codey is no longer probed.
  That is acceptable: Grafana down means no alerts at all. `check-server-status` covers
  monitor.lehel.xyz externally.

### Two authenticated cross-host routes (the only new network surface)
Loki was deliberately taken off Traefik because it has no auth (see the compose comment).
Both new routes must carry **Traefik basicAuth + ipAllowList**, on `websecure` only, with
no `web` router.
1. **servy → codey: Loki push + query** at `loki.lehel.xyz` (codey Traefik → `monitor.loki:3100`).
   Allowlist servy v4 49.13.6.173 (+ servy v6). Users: promtail push, fail2ban query,
   Prometheus scrape of `/metrics`.
2. **codey → servy: Prometheus query** at `prometheus.lehel.xyz` (servy Traefik →
   `monitor.prometheus:9090`). Allowlist codey v4 138.2.180.191 + v6
   2603:c020:802e:5f01:0:876f:f045:3504. User: Grafana datasource.
- Credentials: add literal random values in `ansible/plays/vars/secrets.yml` (git-crypt),
  e.g. `monitor_remote_auth: {loki_password, prometheus_password}`. **Do not** use
  `lookup('password', 'vars/.…')` seed files. CLAUDE.md rule 6 documents that drift hazard.
  Render the htpasswd for the Traefik middleware the way `traefik/dashboard-auth.htpasswd`
  is done.
- The allowlist is defence in depth only. CLAUDE.md warns that servy's Traefik may see v6
  clients as 172.18.0.1 when the proxy network lacks IPv6. Verify the source IP each
  Traefik actually logs for the other host before relying on it. If it is masked, keep
  basicAuth as the control and document it.
- TLS: confirm codey's Traefik `letsencryptdnsresolver` can issue for `lehel.xyz`
  (main Porkbun account `dachrisch`) for monitor.lehel.xyz and loki.lehel.xyz.

### Config changes (keep committed files free of secrets and Jinja)
Follow the existing pattern: secrets are rendered by Ansible into the **untracked**
`monitor/rendered/` dir and bind-mounted read-only (see `plays/user.yml` ~L136-206 and
`history/2026-11-18_monitor-render-out-of-checkout.md`).
- **Grafana datasources**: Prometheus becomes `https://<prometheus host>` with basicAuth,
  so the file now holds a secret. Move it to a template rendered into
  `rendered/datasources.yml` and mount it over
  `provisioning/datasources/datasources.yml`, as contact-points already are. Loki stays
  `http://loki:3100` (same project on codey).
  **Keep uids `prometheus` and `loki`.** The alert rules reference them.
  Add an assert like the contact-points one: no raw `{{`.
- **promtail.yml** (servy): client url → `${LOKI_PUSH_URL}` with `-config.expand-env=true`.
  Set `basic_auth: {username: promtail, password_file: /etc/promtail/loki-password}`,
  rendered to `rendered/loki-password` and mounted ro. Tenant id unchanged.
  `LOKI_PUSH_URL` comes from monitor's env (prod `https://loki.lehel.xyz/loki/api/v1/push`;
  servyy-test its own loki host through local Traefik, so the auth path is tested too).
- **prometheus.yml** `loki` job: replace `loki:3100` with `file_sd_configs` from
  `rendered/loki-target.json`, plus `scheme: https` and
  `basic_auth.password_file: /etc/prometheus/rendered/loki-password`. Add both to
  `world_readable_paths_by_service.monitor` (Prometheus runs as uid 65534, monitor
  AGENTS.md invariant 2/4).
- **fail2ban** `roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2`:
  replace the docker-IP / `monitor.lehel.xyz/loki` fallback with the Loki URL var +
  `curl -u` using the rendered credential (file mode 0600 root). Keep the tenant header.
- `monitor_reload` fingerprints must include the new rendered files for the container that
  reads them: datasources → grafana; loki-target/password → prometheus.

### Cleanup on servy (fresh start, nothing kept)
After servy is redeployed with the `collect` profile, Ansible tasks (gated on
`'ui' not in monitor_profiles`) remove containers `monitor.grafana`, `monitor.loki` and
volumes `monitor_grafana_data`, `monitor_loki_data`. Compose does not remove services
whose profile is inactive, so this must be explicit. It must be idempotent and must not
touch other volumes.

## Delegation to the local opencode session
Claude does not implement this itself. Once the plan is approved, Claude hands it to the
local opencode background service (`opencode serve --service`, v2.3.2, already running on
this workstation):

1. Copy this plan into the repo as `docs/plans/2026-11-20_grafana-to-codey.md`, so the
   opencode worktree can read it and it gets committed with the change.
2. Start the session in its own worktree, in the background:
   ```bash
   cd /home/cda/dev/infrastructure/container
   opencode run --worktree grafana-to-codey --title "grafana+loki → codey" \
     -f docs/plans/2026-11-20_grafana-to-codey.md \
     "Execute the attached plan end to end. Read CLAUDE.md and monitor/AGENTS.md first.
      Branch claude/grafana-to-codey. Test on servyy-test before anything else.
      STOP and ask before every production deploy (codey, servy) and every DNS change.
      Never scp/rsync or hand-edit on servers. Report each verification result verbatim."
   ```
   - **No `--auto`**: permission prompts and the prod/DNS approval questions surface in your
     opencode UI. Attach with `opencode -s <session-id>` (Claude reports the id).
   - The opencode session has no `dns-master` agent. For steps 3 and 6 it asks you, and you
     run the DNS change (or have Claude do it via dns-master).
3. Claude watches the run (background Bash notification on exit). It relays the session id,
   progress and the final verification results, and reviews the resulting diff against
   this plan before the merge in step 7.

## Execution order (performed by the opencode session)
Work on branch `claude/grafana-to-codey` (worktree). Follow CLAUDE.md: test first, no
scp/rsync/manual edits on servers, and **stop and ask the user before every production
deploy and every DNS change**. After the rollout, prod checkouts must be back on `master`.

1. Implement the above. Add/extend Molecule coverage for the profile gating
   (`docker_service` / `monitor_reload` scenarios). Run `ansible-playbook servyy.yml --syntax-check`,
   `.github/scripts/validate-git-crypt.sh` and `check_published_ports.py`.
2. **servyy-test** (`scripts/setup_test_container.sh`, `ansible/servyy-test.sh --tags user.docker.repo,user.docker.monitor,system.probe,fail2ban`).
   Both profiles run there, but promtail, Grafana and Prometheus use the **Traefik routes**,
   not the docker network. Verify everything in the checks below.
3. **DNS (ask user; dns-master):** create `loki.lehel.xyz CNAME codey.lehel.xyz`.
   `prometheus.lehel.xyz` is already covered by the `*.lehel.xyz → servy` wildcard; verify it resolves.
4. **codey (ask user):** `./servyy.sh --limit codey.lehel.xyz --tags user.docker.repo,user.docker.monitor`.
   Verify Grafana with `curl --resolve monitor.lehel.xyz:443:138.2.180.191 https://monitor.lehel.xyz/api/health`
   and the admin API returning 200. Use a temporary datasource test once the servy route is live.
5. **servy (ask user):** `./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.monitor,system.probe,fail2ban`.
   This switches promtail to the remote Loki, opens the Prometheus route, and removes the
   old grafana/loki containers and volumes.
6. **DNS (ask user):** `monitor.lehel.xyz CNAME codey.lehel.xyz`. It overrides the wildcard for this name only.
7. Merge to master, push, then redeploy both hosts with `--tags user.repo.clone` so both
   checkouts are on master.
8. Docs in the same change: `monitor/AGENTS.md` (two-host split, profiles, routes),
   CLAUDE.md (Key Services table, Loki curl examples now `loki.lehel.xyz` with auth,
   Quick Reference `docker restart monitor.grafana` → on codey, stale codey IP
   217.217.227.124), the `check-server-status` skill table, the servy-landscape map, and
   `history/2026-11-20_grafana-loki-to-codey.md`.

## Verification (each environment)
- `docker ps` on codey: monitor.grafana + monitor.loki healthy. On servy: no monitor.grafana/loki,
  collect containers healthy, `docker volume ls | grep -E 'monitor_(grafana|loki)_data'` empty.
- Grafana API: datasources `prometheus` and `loki` health OK. `/api/v1/provisioning/alert-rules`
  count equals the count before the move (record it first on servy). All rules evaluating, none in error.
- Loki on codey receives servy logs: query_range `{job="docker",container="traefik.traefik"}` returns lines < 1 min old.
- Prometheus on servy: `up{job="loki"} == 1`, all other targets still up.
- `sudo bash /usr/local/bin/blocklist/update-from-loki.sh` on servy runs without error and queries the remote Loki.
- Container-health probe: `system_container_health_probe_success 1`, and no `system_container_running 0`
  for monitor.* in Pushgateway. The `container_not_running` alert is Normal.
- Negative tests: `curl https://loki.lehel.xyz/loki/api/v1/labels` without auth → 401.
  From a third IP with auth → 403. Same for prometheus.lehel.xyz.
- Send a contact-point test notification from Grafana on codey (SMTP egress from Oracle on 587).
- `ssh lehel.xyz "df -h /mnt/servy-docker-data; free -m"`: expect about 4 GB freed after the weekly prune and less swap.
- `check-server-status` skill on both hosts.
