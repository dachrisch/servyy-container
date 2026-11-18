# monitor/ — Prometheus, Grafana, Loki, cAdvisor, Pushgateway

The observability stack for servy. One compose project (`name: ${SERVICE_NAME}` =
`monitor`), all internal: nothing here publishes a port except the Pushgateway bridge on
`127.0.0.1:9091`, which is how the host probes (`~/.system-probes/*.sh`) push their gauges.

| Container | Image | Purpose |
|---|---|---|
| `monitor.prometheus` | `prom/prometheus:latest` | scrape + recording rules; **not** published on the host |
| `monitor.grafana` | `grafana/grafana:latest` | dashboards + alert rules (file-provisioned) |
| `monitor.loki` / `monitor.promtail` | Grafana Loki stack | logs |
| `monitor.cadvisor` | `cadvisor:latest` | `container_*` metrics (working set, limits, OOM events) |
| `monitor.pushgateway` (+ `monitor.pushgateway-bridge`) | `prom/pushgateway` | probe gauges |

## Load-bearing invariants — do not "clean these up"

1. **Prometheus and Grafana read their config AT STARTUP, not on change.**
   - Prometheus runs **without `--web.enable-lifecycle`**, so there is no `/-/reload`. A changed
     `prometheus.yml` or `rules/*.yml` takes effect only when the container **restarts**.
     `docker_service` recreates it when the compose *spec* changes; a rules-only edit changes no
     spec, so without the reload task the old rules would keep evaluating and nothing would say so.
   - Grafana **polls dashboards and datasources, but not `provisioning/alerting/`**. After editing
     `alert-rules.yml` it keeps evaluating the previous rule set until it restarts. Measured on
     2026-11-18: a deploy left it running 47 of 49 rules.
   - The deploy now handles both: [`plays/tasks/monitor_reload.yml`](../ansible/plays/tasks/monitor_reload.yml)
     fingerprints `prometheus.yml` + `rules/*.yml` and `provisioning/alerting/*.yml` +
     `rendered/contact-points.yml`, compares each with the last applied value under
     `~/.deploy-state/monitor/`, and restarts **only** the container whose startup content changed —
     Prometheus for rules/config, Grafana for provisioning, never each other. It restarts nothing
     when nothing changed, and nothing on the first run (compose has just handed the container the
     new content). Do not "simplify" it to a blanket restart: the host is load-sensitive.
   - Editing these files **by hand on the host** still requires `docker restart` — the task only runs
     inside a `--tags user.docker.monitor` deploy.
2. **A glob Prometheus cannot read matches nothing, silently.** `rule_files: [/etc/prometheus/rules/*.yml]`
   with the directory at `drwxrwx---` (the checkout's umask 007) and Prometheus running as
   `nobody` (65534) loads **zero rule groups** and logs no error — only
   `Finished loading of configuration file … rules=87µs` and `Starting rule manager`. A rule file
   added to `rules/` must therefore be listed in
   [`world_readable_paths_by_service`](../ansible/plays/vars/default.yml) (`monitor: [rules]`), which
   both the `docker_service` role and the repo-sync task apply as `a+rX`. Verify with
   `docker exec monitor.prometheus ls /etc/prometheus/rules/` and
   `/api/v1/rules?type=record` — the second must list the group, `health=ok`.
3. **`container_memory_near_limit` is an alert-rule UID *and* a recorded series.**
   The rule (`alert-rules.yml`, 0.9 of `mem_limit` for 15m, capped containers only) and the recording
   rule (`rules/container-memory.yml`) share one expression, so they cannot disagree. Query the
   series **inside** Prometheus (`docker exec monitor.prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=…'`);
   `127.0.0.1:9091` is the **Pushgateway** and only carries the probes' own gauges — checking there
   and concluding "the metric does not exist" is the mistake this note was written after.
4. **Grafana and Prometheus read bind-mounted checkout files as non-root users** (`472`, `65534`).
   Anything they read must be in `world_readable_paths_by_service`, or the container exits on
   permission denied and silently drops out of the project (2026-10-27, again 2026-11-18).

## Verifying a change took effect

```bash
# Prometheus rules loaded (must list container-memory, health=ok)
ssh servy.lehel.xyz "docker exec monitor.prometheus wget -qO- 'http://localhost:9090/api/v1/rules?type=record'"

# Grafana rule count and the rules you edited (admin password from the container env)
ssh servy.lehel.xyz 'PW=$(docker inspect monitor.grafana -f "{{range .Config.Env}}{{println .}}{{end}}" | sed -n "s/^GF_SECURITY_ADMIN_PASSWORD=//p" | head -1); docker exec -e PW="$PW" monitor.grafana sh -c "curl -s -u admin:\$PW http://localhost:3000/api/v1/provisioning/alert-rules" | grep -c uid'
```

## Layout notes

- `prometheus.yml` — scrape config + `rule_files`. `rules/` — recording rules (mounted read-only).
- `provisioning/alerting/alert-rules.yml` — every alert rule (one file, groups by area).
  `contact-points.yml` is rendered into `rendered/` by Ansible and mounted separately.
- The alert rules and dashboards are provisioned **from this directory**; edits made in the Grafana
  UI are overwritten on the next restart and must be brought back here.
