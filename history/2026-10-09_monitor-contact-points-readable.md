# 2026-10-09 — Monitor contact-points provisioning file must be world-readable

## Symptom

Deploying #186 (`scope db alerting to leaguesphere role and vault monitor
secrets`) took the production monitor stack down: `monitor.grafana`
crash-looped (`Exited (1)`) with

```
failure to parse file contact-points.yml:
open /etc/grafana/provisioning/alerting/contact-points.yml: permission denied
```

## Cause

The new `Render monitor provisioning configs from centralized vars` task in
`ansible/plays/user.yml` rendered `provisioning/alerting/contact-points.yml`
with `mode: '0600'`. The file was left owned by `cda:docker` on the host, but
Grafana runs as `uid 472 gid root` inside the container and reads the file over
the `./provisioning:/etc/grafana/provisioning` bind mount. Neither the group
(`docker`) nor others could read it, so Grafana's provisioning module failed and
the whole service exited.

The molecule `docker_service/default` scenario asserts the rendered env files
and compose config but does not verify that the in-container Grafana user can
read the bind-mounted provisioning file, so CI stayed green.

## Fix

- `ansible/plays/user.yml`: render `contact-points.yml` with `mode: '0644'`
  (matching `promtail.yml` / `datasources.yml`). World-read is confined to the
  container's mount namespace; `/home/cda` traversal is not required.
- Immediate production remediation: `chmod 0644` on the host file and restart
  `monitor.grafana` — service returned to `healthy`.

## Follow-up

A deploy-time check that Grafana can actually read its provisioning files (or a
molecule assert on the rendered mode) would catch this class of bug before
production. Tracked here as a known gap.
