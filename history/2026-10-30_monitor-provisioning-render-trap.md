# ADR: the monitor provisioning render trap — Grafana crash-loops on raw Jinja

**Date:** 2026-10-30
**Status:** Accepted
**Relates to:** [`2026-10-30_load-alert-tuning.md`](2026-10-30_load-alert-tuning.md) (the deploy that exposed it), [`2026-10-29_monitor-restart-policy.md`](2026-10-29_monitor-restart-policy.md) (the monitor stack must not disappear silently)

## Context

While rolling the retuned alert rules out, the deploy checkout on
`servy.lehel.xyz` (`/home/cda/servyy-container`) was fast-forwarded with
`git pull`, and `monitor.grafana` was restarted to pick up the new
`alert-rules.yml`. Grafana came up and immediately **crash-looped: exit code 1
every ~10 s, eight restarts in two minutes**, monitoring blind.

The fatal line:

```
logger=backgroundsvcs.managerAdapter level=error msg="Module failed" module=provisioning
  err="... failure: Datasource provisioning error: yaml: unmarshal errors:
       line 23: cannot unmarshal !!map into string"
Error: ✗ invalid service state: Failed, expected: Terminated, ...
```

Line 23 of `monitor/provisioning/datasources/datasources.yml` was still the raw
Jinja placeholder:

```yaml
      httpHeaderValue1: {{ monitor.loki_tenant }}
```

`{{ ... }}` is a YAML flow mapping, so the file does not parse. Two facts made
this a landmine rather than a mistake:

1. **`docker.remote_dir` *is* a git checkout.** `plays/user.yml` renders three
   monitor files from the controller into that checkout:
   `provisioning/datasources/datasources.yml`, `provisioning/alerting/contact-points.yml`
   and `promtail.yml`. They are tracked files, so on the server they are always
   "modified" relative to git, and any `git pull` (or a checkout that never
   rendered them) puts the raw `{{ … }}` back. `git status` showed a clean tree
   *before* the pull, i.e. the files had already been reverted at 19:02 UTC —
   the pull was not the trigger, the restart was.
2. **Grafana 13 treats a provisioning error as fatal.** It is not a warning that
   leaves the last good config in place: the provisioning module fails to start,
   Grafana exits 1, `restart: unless-stopped` restarts it, repeat. Nothing in the
   compose file or the previous ADRs marked this as a "never restart without
   checking" hazard. Prometheus and Loki kept running throughout — only Grafana
   and therefore all dashboards and alerts were down.

## Decision

Restore the three rendered files on the server from values recovered from **live
state** (the repo cannot supply them — `monitor.loki_tenant` and
`monitor_admin_email` live in git-crypt-encrypted vars that this agent session has
no key for):

| Placeholder | Value | Recovered from |
|---|---|---|
| `{{ monitor.loki_tenant }}` | `servyy-logs-k8x9m2p4q7` | `monitor_loki_data/_data/chunks/` — Loki stores per-tenant chunk directories under the tenant id (also documented in `CLAUDE.md`) |
| `{{ monitor_admin_email }}` | `dachrischx+monitor@gmail.com` | `alert_configuration` in `grafana.db` (the live contact points) and `GF_SMTP_USER` in `grafana.env` |

The rendered `contact-points.yml` also needed the escaped-brace line unescaped
(`{{ '{{' }} .Status …` → `{{ .Status …`), which is what the Ansible render does.

Then `chmod 644` (Grafana runs as uid 472 and only reads world-readable files;
the git pull had also left `alert-rules.yml` at `0660 cda:cda`), restart Grafana,
and verify. The repo itself is unchanged: the templates stay raw Jinja, because
that is what the controller renders.

**Guard:** `CLAUDE.md` gained a "Never `git pull` the deploy checkout on the
server" section naming the three files, the crash signature, and the recovery
path. A normal Ansible deploy re-renders all three and is the sanctioned repair.

## Consequences

### Positive
- Grafana is back: **43 alert rules** provisioned (the 42 existing plus the new
  `node_cpu_pressure_high`), both datasources present, Loki queries work with the
  recovered tenant (labels returned; empty for a wrong tenant), Prometheus `up == 1`.
- The landmine is documented where the next operator will look, instead of
  surviving as tribal knowledge.
- The dependency on git-crypt secrets for recovery is now known to be avoidable:
  both values are recoverable from live state.

### Negative / Tradeoffs
- The server checkout now shows three files as modified against git. That is
  correct and expected, but it means a `git pull --ff-only` there will refuse (or
  silently revert them again if forced). The checkout is a deploy target, not a
  workspace.
- The real fix — rendering into a directory *outside* the checkout — is a
  structural change to the monitor role and the compose bind mounts, and was not
  attempted under incident conditions.

### Known issues
- `notification-policies.yml` and all other monitor files are copied verbatim by
  the role and carry no placeholders, so a pull is harmless for them. Only the
  three above are affected.
- Ansible was not available to run from this session (no controller checkout
  outside git-crypt, no vault key), which is why the repair was applied directly
  to the remote dir instead of by redeploying.

## Implementation details

**Files modified (server, `/home/cda/servyy-container`):**
- `monitor/provisioning/datasources/datasources.yml` — rendered, 0644
- `monitor/provisioning/alerting/contact-points.yml` — rendered, 0644
- `monitor/promtail.yml` — rendered, 0644
- `monitor/provisioning/alerting/alert-rules.yml` — 0644 (content from the merged PR)

**Files modified (repo):**
- `CLAUDE.md` — NEW section: never `git pull` the deploy checkout
- `history/2026-10-30_monitor-provisioning-render-trap.md` — NEW (this file)

**Verification performed:**
- `docker inspect monitor.grafana` → running, healthy, `RestartCount = 0` after the fix
- `GET /api/v1/provisioning/alert-rules` → **43** rules; the six touched rules carry the
  intended `for` / severity / threshold
- `GET /api/datasources` → `prometheus` (http://prometheus:9090) and `loki` (http://loki:3100)
- Loki `GET /loki/api/v1/labels` with `X-Scope-OrgID: servyy-logs-k8x9m2p4q7` → labels returned;
  with a wrong tenant → empty
- `up{job="node-exporter"} == 1` through the provisioned Prometheus datasource
- Grafana log since the successful start: no provisioning errors
- Active alerts after the reload: **0** (the two load alerts and the swap alert
  resolved against the new thresholds — load15 is at 0.79 per core, swap at 54 %)

**Key learnings:**
1. In Grafana 13 a bad provisioning file is **fatal at boot**, not a warning. One
   invalid datasource line takes down every dashboard and alert.
2. The ansible `remote_dir` for the monitor stack is a git checkout, so rendered
   artifacts and git content fight over the same paths. Pulling on the server is
   never safe.
3. `chmod` matters twice: the umask on the server leaves files `0660 cda:cda`
   (Grafana cannot read them) and the pulled file kept that mode.
4. Vault-rendered values are usually recoverable from the running system — Loki's
   chunk directory names the tenant, and Grafana's own DB holds the contact points.
