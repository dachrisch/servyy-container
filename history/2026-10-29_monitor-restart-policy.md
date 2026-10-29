# 2026-10-29 — The monitor stack had no restart policy, so every reboot erased it

## Summary

`monitor.lehel.xyz` had been serving Traefik's 404 with zero monitor containers on the
host: no Grafana, Prometheus, Loki, Promtail, pushgateway, node-exporter or cadvisor —
`docker ps -a` held none of the eight. The stack was not crash-looping; its containers,
both networks and all its images had been **deleted**, and nothing ever brought them
back. Root cause: `monitor/docker-compose.yml` was the only compose file in the repo
without a `restart:` policy, so the unattended-upgrades host reboot left all eight
containers stopped, and the aggressive `docker system prune` that ran seconds later
removed them for good.

## What the evidence showed

| Time (CET) | Evidence |
|---|---|
| 05:00:16 | `unattended-upgrades.log`: `Packages that will be upgraded: linux-image-generic linux-image-virtual linux-libc-dev` |
| 05:01:23 | `WARNING Found /var/run/reboot-required, rebooting` → `Reboot scheduled for Thu 2026-10-29 05:30:00 CET` |
| 05:30:03 | last writes in the monitor volumes: Prometheus WAL, Loki WAL + chunks, Promtail `positions.yaml`, `grafana.db` — containers stopping, flushing state |
| 05:30:31 | `uptime -s` → host booted (kernel `7.0.0-42-generic`) |
| 05:31:05 | `docker-cleanup.service` started (`TriggeredBy=docker-cleanup.timer`) and ran `docker system prune -a -f --volumes` |
| 05:31:47 | cleanup log: `Deleted Containers:` **8 hashes**, then `Deleted Networks: monitor_backend, monitor_pushgateway_publish`, then `Deleted Images: grafana/grafana, grafana/loki, grafana/promtail, prom/prometheus, prom/pushgateway, prom/node-exporter, gcr.io/cadvisor, alpine/socat` |

`monitor/docker-compose.yml` contained **zero** `restart:` directives, while every other
service in the repo (`traefik`, `searxng`, `moodle`, `finance`, …) carries
`restart: unless-stopped`. Without a policy Docker does not restore containers after a
daemon restart, they stay in `Exited` state — and `docker system prune` deletes stopped
containers before it prunes images. The volumes survived (the prune reported them as
reclaimable but left them), so no history was lost.

The cleanup timer is `Persistent=true`, so a run that systemd considers missed is
executed on boot — which is why an aggressive prune landed 35 seconds after the host
came up, i.e. exactly when the policy-less containers were sitting stopped.

## Second defect found while restarting

`promtail` and `grafana` crash-looped on the first start even after the containers were
recreated:

```
Unable to parse config: /etc/promtail/config.yml: yaml: unmarshal errors:
  line 11: cannot unmarshal !!map into string
provisioning: Datasource provisioning error: yaml: unmarshal errors:
  line 23: cannot unmarshal !!map into string
```

`monitor/promtail.yml`, `monitor/provisioning/datasources/datasources.yml` and
`monitor/provisioning/alerting/contact-points.yml` are **Jinja templates tracked in git**
that ansible renders onto the same path inside the checkout. Any checkout/`git pull`
that touches those files restores the raw `{{ … }}` text; the running containers keep
their in-memory config until the next restart, and then fail to parse. That is why a
plain `docker compose up -d` was not enough here: the ansible render task
(`user.docker.env.monitor`) has to run first.

## Fix

- `monitor/docker-compose.yml`: `restart: unless-stopped` on all eight services.
- Restart path used: `git pull` on the host, then
  `ansible-playbook servyy.yml -i production --limit servy.lehel.xyz \
   --tags user.docker.env.monitor,user.docker.monitor` (renders the three config files,
  then converges the compose project). `ok=24 changed=2 failed=0`.

## Verification

```
monitor.grafana             Up (healthy)   restart=unless-stopped
monitor.loki                Up             restart=unless-stopped
monitor.promtail            Up             restart=unless-stopped
monitor.prometheus          Up (healthy)   restart=unless-stopped
monitor.pushgateway         Up             restart=unless-stopped
monitor.pushgateway-bridge  Up             restart=unless-stopped
monitor.node-exporter       Up (healthy)   restart=unless-stopped
monitor.cadvisor            Up (healthy)   restart=unless-stopped

https://monitor.lehel.xyz/api/health -> 200 {"database":"ok","version":"13.3.0"}
https://monitor.lehel.xyz/           -> 302 (login)
Prometheus targets: cadvisor, loki, node-exporter, prometheus, pushgateway, traefik = up
Loki /ready = ready; labels present under tenant servyy-logs-k8x9m2p4q7
Promtail: 429 ingestion backlog cleared, 0 send errors after catch-up; Grafana
provisioning errors only from the pre-render crash, 0 after the render
```

Host after the restart: 4.0 GiB of 7.6 GiB used, 3.5 GiB available, monitor stack
~990 MiB total RSS (loki 362, grafana 284, prometheus 201, rest <100 each).

## Follow-up (not done here)

1. **`docker-cleanup.service` runs on every boot** (`WantedBy=multi-user.target` plus a
   `Persistent=true` timer). The timer already covers the daily 02:00 schedule; the boot
   trigger is what turned a stopped container into a deleted container. It also runs
   `--volumes` against a host whose data volumes are one `prune` away from loss. Worth
   dropping the boot trigger, or at least gating the prune on containers older than N
   minutes.
2. **Rendered config on tracked paths.** Rendering `promtail.yml`,
   `datasources.yml` and `contact-points.yml` over the git checkout means the next
   checkout silently reverts them and the containers crash-loop on their next restart
   (Grafana refused to provision data sources, Promtail refused to parse). Render into
   an untracked location (e.g. `monitor/rendered/`) and mount that, or mark the paths
   `skip-worktree` on the host.
3. **Prod checkout was 5 commits behind** `master` (docs-only effect) and is synced to
   `a54c230` by this work.
