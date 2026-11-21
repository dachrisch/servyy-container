# monitor/ — Prometheus, Grafana, Loki, cAdvisor, Pushgateway

The observability stack for the fleet. **One compose project, two hosts, two
compose profiles** (since 2026-11-20). Container names are unchanged
(`monitor.grafana`, `monitor.loki`, …); the profile decides which half a host
runs, and `monitor/.env` carries it as `COMPOSE_PROFILES`:

| Profile | Services | Host | Why there |
|---|---|---|---|
| `ui` | `grafana`, `loki` | **codey** | Alerting must survive a servy outage; Loki is where servy's logs are shipped to. |
| `collect` | `prometheus`, `pushgateway` (+`pushgateway-bridge`), `node-exporter`, `cadvisor`, `promtail` | **servy** | Every one of them reads *servy*: `/proc`, `/sys`, the Docker socket, `/var/log`, and the probes push to `localhost:9091`. |

`servyy-test.lxd` runs **both** profiles, so the cross-host routes and their auth
are rehearsed before production — though there the clients connect over the docker
network (`loki:3100`, `prometheus:9090`) because a `.lxd` name does not resolve
inside a container; the routes are exercised with curl. Nothing here publishes a
port except the Pushgateway bridge on `127.0.0.1:9091` and the two authenticated
routes below.

| Container | Image | Purpose | Host |
|---|---|---|---|
| `monitor.prometheus` | `prom/prometheus:latest` | scrape + recording rules; query API on `prometheus.lehel.xyz` (basicAuth) | servy |
| `monitor.grafana` | `grafana/grafana:latest` | dashboards + alert rules (file-provisioned), `monitor.lehel.xyz` | codey |
| `monitor.loki` | `grafana/loki:latest` | logs; ingest/query on `loki.lehel.xyz` (basicAuth) | codey |
| `monitor.promtail` | `grafana/promtail:latest` | ships servy's container + system logs to Loki | servy |
| `monitor.cadvisor` | `cadvisor:latest` | `container_*` metrics (working set, limits, OOM events) | servy |
| `monitor.pushgateway` (+ `monitor.pushgateway-bridge`) | `prom/pushgateway` | probe gauges | servy |
| `monitor.node-exporter` | `prom/node-exporter` | host CPU/mem/disk | servy |

## The only network surface between the hosts — do not widen it

Two Traefik routes carry all cross-host monitor traffic. Loki was deliberately
taken off Traefik in 2026-09 because it had no auth; it is back only behind
**basicAuth + ipAllowList**, on `websecure` only (no `web` router):

| Route | Host serving it | Who calls it | Auth user |
|---|---|---|---|
| `loki.lehel.xyz` | codey → `monitor.loki:3100` | servy's promtail (push), servy's Prometheus (`/metrics`), fail2ban on servy **and** codey (query) | `promtail` |
| `prometheus.lehel.xyz` | servy → `monitor.prometheus:9090` | codey's Grafana datasource | `grafana` |

- The credentials are literal values in `plays/vars/secrets.yml`
  (`monitor_remote_auth`) — **not** `lookup('password', 'vars/.…')` seeds, which
  exist only on one controller and would silently rotate on a fresh checkout
  (CLAUDE.md rule 6). `roles/monitor_remote_auth` hashes them into
  `traefik/monitor-{loki,prometheus}-auth.htpasswd`; the plaintext is rendered
  into `monitor/rendered/` (`loki-password`, `datasources.yml`) and into the
  fail2ban helper (installed `0700 root`).
- `ipAllowList` is defence in depth: servy `49.13.6.173` /
  `2a01:4f8:c013:f6f4::1`, codey `138.2.180.191` /
  `2603:c020:802e:5f01:0:876f:f045:3504`. Codey is on the Loki list because its
  own `loki-blocklist` jail polls the same Loki. Verify the address each Traefik
  actually logs before trusting the list (a v6 client is masked as `172.18.0.1`
  if the proxy network lacks IPv6; it carries IPv6 on both hosts since
  2026-11-11). Ranges are per host in `monitor/.env` (`MONITOR_*_ALLOW`) because
  `traefik/dynamic.yaml` is shared and servyy-test reaches itself privately.
- Middleware order is auth → allow, so an unauthenticated request is **401** and
  an authenticated one from a stranger is **403**.
- TLS: production uses `MONITOR_TRAEFIK_ENTRYPOINT=websecure` +
  `letsencryptdnsresolver` (Porkbun DNS-01, main `dachrisch` account); servyy-test
  uses plain `web`. Grafana's own router follows the same three vars. The
  inventory-only `monitor_local_traefik` selects the test shape — keep it out of
  `vars/default.yml`: play vars_files outrank inventory host vars, so a key
  defined there can never be overridden per host.

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
     fingerprints `prometheus.yml` + `rules/*.yml` + `rendered/loki-target.json` +
     `rendered/loki-password` and `provisioning/alerting/*.yml` +
     `rendered/contact-points.yml` + `rendered/datasources.yml`, compares each with the
     last applied value under `~/.deploy-state/monitor/`, and restarts **only** the
     container whose startup content changed — Prometheus for rules/config, Grafana for
     provisioning, never each other. It restarts nothing when nothing changed, and nothing
     on the first run (compose has just handed the container the new content). Do not
     "simplify" it to a blanket restart: the host is load-sensitive.
   - Since the split it also runs **only half the role per host**
     (`monitor_reload_{prometheus,grafana}_enabled` from `monitor_profiles`): grafana is
     not on servy and prometheus is not on codey, so inspecting/restarting the other
     half's container would fail the deploy.
   - Editing these files **by hand on the host** still requires `docker restart` — the task
     only runs inside a `--tags user.docker.monitor` deploy.
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

5. **`alert-rules.yml` names no tenant, repo, log or threshold — and must not start.**
   The probes publish the policy they are judged by
   (`restic_snapshot_threshold_seconds{repo}`, `restic_snapshot_severity{repo}`,
   `db_dump_threshold_seconds{tenant,tier}`, `db_dump_severity{tier}`,
   `system_log_threshold_seconds{log}`), all generated from
   `ansible/plays/vars/db_tenants.yml`, and the backup rules are comparisons:

   ```promql
   ((restic_snapshot_age_seconds > on(repo) group_left() restic_snapshot_threshold_seconds)
    or ((restic_snapshot_age_seconds < bool 0) > 0))
   and on(repo) (restic_snapshot_severity == 1)     #  == 0 for the medium rule
   ```

   The restore drills (WP-8R R11) follow the same rule: the probe
   `~/.restore-drills/restore-drill-probe.sh` publishes `db_restore_drill_age_seconds{tenant}`,
   `db_restore_drill_success{tenant}`, `db_restore_drill_duration_seconds{tenant}`
   and `db_restore_drill_threshold_seconds{tenant}` (the cadence from the row's
   `drill:` field — 8 d weekly, 32 d monthly), and `db_restore_drill_overdue`
   compares them. `drill: none` tenants emit no series, so a legitimate opt-out
   (nonprod) can never page. Do not add a tenant name or a number to those rules
   either; a drill that silently stops is the failure the rules exist for, so
   `db_restore_drill_probe_stale` must stay too (a dead probe freezes every age
   and would otherwise look like a healthy fleet).

   One more Pushgateway trap, measured 2026-11-19: a push it **rejects** (a
   hand-made payload without `# TYPE`, or a per-tenant path like
   `/metrics/job/db_restore_drill/tenant/moodle`) still creates that group with
   `push_time_seconds 0`. `time() - 0` is ~56 years, so `db_restore_drill_probe_stale`
   fired for eight minutes against a healthy probe. The rule now filters
   `push_time_seconds > 0`; when you test a rule by hand, push to a **separate job
   name**, then `curl -X DELETE http://127.0.0.1:9091/metrics/job/<that-job>` and
   confirm `count(db_restore_drill_age_seconds)` is back to 8, not 9.

   Two rules per class (high / not-high), because a Grafana rule has **one static
   `labels.severity`**; the split has to travel as a series. Until WP-8R R2 these were `or`
   chains of literals, so five repos with dumps, timers and snapshots ran unalerted — a
   new row here must never need an edit. `on(...) group_left()` is a *join*: a series with
   no threshold series matches nothing, i.e. it is silently unmonitored, which is why the
   deploy must confirm the threshold series exist for every repo/tenant.

   **`< bool 0`, not `< 0`.** The probes push `-1` for "unverifiable" (no repo state, no
   dump directory). Grafana's threshold expression maps `-1` to **0 = not met** (measured
   with `POST /api/v1/eval`: `-1`→0, `0`→0, `8486`→1), so a literal `< 0` clause is
   silent, which is exactly what the `-1` was supposed to prevent. `(x < bool 0)` turns it
   into a positive 1 before the rule's own `> 0.5` threshold.

   Verify after a deploy (read-only):

   ```bash
   ssh servy.lehel.xyz "docker exec monitor.prometheus wget -qO- \
     'http://localhost:9090/api/v1/query?query=restic_snapshot_threshold_seconds' | grep -o 'repo=[^}]*' | wc -l"
   ssh servy.lehel.xyz "docker exec monitor.prometheus wget -qO- \
     'http://localhost:9090/api/v1/query?query=db_dump_threshold_seconds' | grep -o 'tenant=[^,}]*'"
   ```

   Both must list every repo / tenant that has a probe; a short list is a silent outage.
   The expressions can be parsed without deploying — dump them into a Prometheus rule file
   (`data[0].model.expr` → `expr:`) and run `promtool check rules`; the running
   `monitor.prometheus` container ships `promtool`.

   **The snapshot age is the maximum over the WHOLE repo.** `restic snapshots --latest 1`
   returns the newest snapshot per `(hostname, paths)` **group**, so reading `[0]` reports
   whichever group sorts first, not the newest snapshot. Measured 2026-11-18: a stray
   `hostname="localhost"` snapshot (left by a branch-rendered test, since forgotten) formed its
   own group and `repo="home"` reported 10 440 s while the real newest was 1 612 s old — a
   medium alert that could never clear. The probe now takes `max(.time)` across
   `restic snapshots --json`; `ansible/tests/system_probe/test_restic_snapshot_probe.py` runs
   the rendered script against a two-group fixture and fails if `[0]`-style behaviour returns.

   **Dump-age coverage per tenant (2026-11-18):** seven tenants emit `db_dump_age_seconds` —
   photoprism, leagues_finance, queen, dontforget, firefly, plus `bnb_office` (rides the `home`
   snapshot, where a failed dump is otherwise invisible) and `leaguesphere` (the mariadb-backup
   prepared set, whose directory mtime is the hourly atomic swap). `moodle` deliberately has no
   row: its dump directory sits under a `0750 root:root` parent and the probe runs as the
   unprivileged user, so `stat()` is refused and a row would page `-1` forever; that condition
   is covered instead by the `moodle-db` stale-source guard, which fails the snapshot job
   (`stale_restic_snapshot_high`). The nonprod tier emits nothing by design.

   **Moodle tasks (2026-11-21).** A second kind of blind spot: Moodle's cron writes to
   `/dev/nulll` inside the image (a typo in its runit script), so a failing task leaves nothing in
   `docker logs`, and the container stays `healthy` throughout. `moodle-task-failures.sh`
   (`job="moodle_task_failures"`, every 5 min, only where `moodle_enabled`) reads
   `mdl_task_log` plus the retry state through `php` **inside the container** — no DB credentials
   on the host — and pushes `moodle_task_failures{window}`, `moodle_task_needs_attention`
   (parked ad-hoc + failing scheduled) and their thresholds, plus `moodle_task_probe_success`.
   The alert group is `moodle-alerts`; the high rule is the state behind Moodle's own
   "Die Task … ist mehrmals fehlgeschlagen" mail, the medium one catches 2+ failed runs in the
   hour. Provenance of the design: `history/2026-11-21_moodle-task-failure-probe.md`.

   **Those two rules use `instant: true`, and that is load-bearing.** Nearly every other rule in
   this file is a range query + `reduce: last`, which is right for a series that always exists
   (an age, a freshness, a `probe_success`). A *comparison that is empty when healthy* is not:
   after the condition clears, the range query keeps returning the last positive sample for the
   whole `relativeTimeRange` (300 s), so the rule measures `for: + 5 min` and one failing probe
   run is enough to page. Measured live on 2026-11-21 while testing this probe: a synthetic `1`
   that was overwritten ~3 minutes earlier still produced `state: firing` and a notification,
   because every evaluation reduced the same stale sample. Instant queries take one point, so a
   cleared condition resolves on the next evaluation and `for:` means exactly itself.

## Verifying a change took effect

```bash
# Prometheus rules loaded (must list container-memory, health=ok)
ssh servy.lehel.xyz "docker exec monitor.prometheus wget -qO- 'http://localhost:9090/api/v1/rules?type=record'"

# Grafana rule count — Grafana lives on codey now
ssh codey.lehel.xyz 'docker exec monitor.grafana sh -c "\
  curl -s -u admin:\$GF_SECURITY_ADMIN_PASSWORD \
  http://localhost:3000/api/v1/provisioning/alert-rules" | jq length'

# …and that the rules are still EVALUATING (every health must be "ok",
# every rule must carry a lastEvaluation timestamp)
ssh codey.lehel.xyz 'docker exec monitor.grafana sh -c "\
  curl -s -u admin:\$GF_SECURITY_ADMIN_PASSWORD \
  http://localhost:3000/api/prometheus/grafana/api/v1/rules"'

# The cross-host datasource: codey's Grafana → servy's Prometheus
ssh codey.lehel.xyz 'docker exec monitor.grafana sh -c "\
  curl -s -u admin:\$GF_SECURITY_ADMIN_PASSWORD \
  http://localhost:3000/api/datasources" | jq -r ".[] | .uid + \" \" + .url"'
```

**401 is a trap, not a wrong password.** Grafana applies
`GF_SECURITY_ADMIN_PASSWORD` **only when it creates the admin user** (first boot of a fresh
`grafana_data` volume); after that the credential lives in `grafana.db` and can move without
the env (UI change, the `/user/password/reset` flow, `grafana cli admin reset-admin-password`).
Measured 2026-11-18: env == rendered `grafana.env` == controller seed, but the admin row was
rewritten at 22:12:49 by a browser password reset, so every recipe that authenticated with the
env value answered 401 — and verification fell back to reading `grafana.db` by hand.
`roles/monitor_grafana_auth` now closes that: on a monitor deploy it authenticates with the
container's own env value and, **only** on a 401, re-asserts it into the DB
(`grafana cli admin reset-admin-password --password-from-stdin`, the secret piped inside the
container — never on a command line, never in a log), then fails the deploy unless the API
answers 200. Consequences: a repair logs every open admin browser session out, and a
deliberate UI password change is reverted by the next `--tags user.docker.monitor` deploy —
the rendered value is the credential; the Vaultwarden copy (`grafana - admin (lehel.xyz)`) is
the recovery path. The row's `updated` column in `grafana.db` (`user` table) is the only
evidence of when the credential last moved.

## A rule that leaves `alert-rules.yml` is NOT deleted by Grafana

Classic file provisioning adds and updates rules; it never prunes one that disappears from the
file. Measured on 2026-11-18: `stale_restic_db_snapshot` was removed from `alert-rules.yml` in
WP-8R R2, survived the deploy's Grafana restart (container started 22:24, file edited 20:41),
and kept evaluating — an orphan whose expression still named `repo="db"`/`repo="moodle-db"`, so
a stale `db` repo would have paged **twice** (orphan + `stale_restic_snapshot_high`).

The provisioning API refuses to remove it, in both directions, because the stored provenance
is `classic-file-provisioning`:

```
DELETE /api/v1/provisioning/alert-rules/{uid}
  -> 409 alerting.provenanceMismatch "needs 'classic-file-provisioning'"
PUT    …/{uid}  with X-Disable-Provenance: true
  -> 409 alerting.provenanceMismatch "provided provenance '', needs 'file'"
```

So removal is a DB operation: stop `monitor.grafana`, delete the rule's rows from
`grafana.db` (`alert_rule` where `uid=…`, plus `alert_rule_version`, `alert_rule_state` and
`provenance_type` where `record_key=…`), start it, and verify (53 rules, the uid `404`, no
duplicate uid, all rules `health=ok`). Do this from a copy of the DB outside the container and
restore it with uid/gid `472:0`, mode `0640` — Grafana runs as 472 and will not start on a
root-owned DB. Before that, the honest alternative is to leave the rule in the file.

## Layout notes

- `prometheus.yml` — scrape config + `rule_files`. `rules/` — recording rules (mounted read-only).
- The `loki` scrape job has no `static_configs` any more: host+scheme come from the
  Ansible-rendered `rendered/loki-target.json` (`file_sd_configs`), because production
  scrapes `https://loki.lehel.xyz:443` and servyy-test its own Traefik over `http`.
  `file_sd` labels cannot set `__scheme__` (Prometheus overwrites it from the scrape
  config before relabeling), hence the one `relabel_configs` rule copying
  `loki_scheme` → `__scheme__`. The file must stay strict JSON — the `.json`
  extension selects Prometheus' JSON parser, which rejects comments.
- `provisioning/alerting/alert-rules.yml` — every alert rule (one file, groups by area).
  `contact-points.yml` is rendered into `rendered/` by Ansible and mounted separately.
- `provisioning/datasources/datasources.yml` is the **Jinja source** — Ansible renders
  it to `rendered/datasources.yml`, and compose mounts that over the tracked path. It
  carries the `prometheus.lehel.xyz` basic-auth password; keep the datasource `uid`s
  (`prometheus`, `loki`) or every alert rule and dashboard breaks.
- `promtail.yml` pushes to `${LOKI_PUSH_URL}` (from `monitor/.env`,
  `-config.expand-env=true`) with `basic_auth.password_file`. Its `tenant_id` is the
  public tenant literal.
- The alert rules and dashboards are provisioned **from this directory**; edits made in the Grafana
  UI are overwritten on the next restart and must be brought back here.
