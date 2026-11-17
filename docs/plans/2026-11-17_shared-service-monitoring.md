# Shared-service monitoring Implementation Plan

> **For agentic workers:** implement task by task, in a dedicated worktree/branch.
> Do NOT edit `ansible/plays/vars/secrets.yml` (git-crypt → binary diff → an
> unresolvable merge conflict if another session touches it too).

**Goal:** make the `shared` data layer (mongo/valkey/postgres) actually monitored —
it is currently invisible to every "is it up" signal, and container health
(`running` vs `healthy`) is not surfaced for any container on the host.

**Architecture:** extend the existing pushgateway probe
(`system_probe/templates/system_container_health.sh.j2`) to (a) also check a
backend-only service list, (b) emit a `tier` label, and (c) emit a second metric
`system_container_healthy` from the same `docker inspect` call it already makes
(no extra `docker exec` churn — see `history/2026-10-30_load-alert-tuning.md`).
Then add two Grafana rules to the existing `container-health-alerts` group:
`backend_container_down` (critical) and `container_unhealthy` (medium).

**Tech Stack:** Ansible (`system_probe` role, molecule docker driver),
Docker healthchecks, Pushgateway (PUT semantics), Grafana file provisioning
(`monitor/provisioning/alerting/alert-rules.yml`), Prometheus/cAdvisor.

---

## Current state (verified on servy 2026-11-17)

- `shared.mongo` (mongo:9.0.8), `shared.redis` (valkey 9), `shared.db`
  (postgres 15) serve leagues-finance, queen **and** dontforget since
  2026-11-17 (`history/2026-11-17_dontforget-shared-mongo.md`).
- The container-health probe is built from `docker.services`
  (`ansible/plays/vars/secrets.yml:68`), which contains **no `shared` entry and
  no `dontforget` entry** — neither has ever been probed. The deployed script
  `/home/cda/.system-probes/system-container-health.sh` has 34 `check_container`
  calls and zero of them is a shared container.
- The probe only reads `.State.Running`. A container that is up but whose
  healthcheck fails (`unhealthy`) is reported as `running=1` — i.e. `mongo` can
  stop answering and every signal stays green. The only health-adjacent alerts
  are `container_memory_near_limit` (90% of `mem_limit`, 15m) and
  `up{job="cadvisor"} == 0`; neither sees Docker health.
- cAdvisor already reports these containers (`container_last_seen`,
  `container_memory_working_set_bytes` with `name="shared.mongo"`), so memory
  headroom against the 512m `mem_limit` is covered — nothing to add there.

### The gap, precisely

| Signal | Today | After |
|---|---|---|
| shared container exited | **nothing** | `backend_container_down` (critical) |
| shared container `unhealthy` | **nothing** | `container_unhealthy` (medium) |
| app container `unhealthy` | nothing | `container_unhealthy` (medium) |
| app container exited | `container_not_running` | unchanged |
| memory vs `mem_limit` | `container_memory_near_limit` | unchanged |
| host disk, restic freshness | covered | unchanged |

## Decisions

1. **A separate backend list, not an entry in `docker.services`.**
   `docker.services` also drives Pi-hole `custom.list` DNS (`roles/user/tasks/dns.yml`),
   `test_host.sh` URLs (`roles/user/tasks/host_ping.yml` — it would create a
   `https://shared.lehel.xyz` check that can never pass) and servyy-test
   `/etc/hosts` (`roles/testing/tasks/resolve.yml`). Adding `shared` there
   creates three broken artefacts to save one line elsewhere.
   Rejected alternatives:
   - `- {dir: shared, backend: true}` inside `docker.services` + filters in all
     three consumers: more edits, and each consumer has its own edge cases.
   - Deriving the list from `services_enabled`: the probe runs in
     `plays/system.yml`, where the `services` fact from `plays/user.yml` does not
     exist, and `services_enabled` values are mixed shape (`true` vs
     `{enabled: true}`).
   - Putting the list under `docker:` in `secrets.yml` (next to `services`):
     semantically right, but that file is git-crypt encrypted (binary diff) and
     another session is active — a top-level key in `plays/vars/default.yml`
     stays mergeable. Note Ansible does **not** deep-merge `vars_files`: a
     `docker:` key in `default.yml` would be clobbered by `secrets.yml`, which
     is why the new key is top-level (`docker_backend_services`).
2. **One `inspect` per container.** Combine running + health into a single
   `--format`. A second call per container would double the `docker exec` load
   the host was explicitly tuned to reduce.
3. **`system_container_healthy` is emitted only while the container runs.**
   A stopped container keeps `system_container_running 0` (existing alert) and
   drops out of `system_container_healthy`, so one failure does not page twice.
4. **`tier` label instead of hardcoding `shared` in PromQL.** The alert then
   covers any future backend service without a rule change.
5. **Not cAdvisor-only.** `time() - container_last_seen{name=~"shared\\..*"} > 120`
   would need no Ansible work, but it duplicates liveness detection that already
   lives in the probe, adds a second mechanism for the same question, and still
   cannot see Docker health.

## Out of scope (deliberate)

- **Volume size / growth** for `shared_mongo_data`, `shared.redis`,
  `finance/db`: `node_filesystem_*` alerts already cover `/` and
  `/mnt/servy-docker-data` (alert-rules `:768`, `:1103`); per-volume `du` probes
  cost more than they catch today (mongo db = 1.05 MB, pg = 0.76 MB).
- **Application-level ping** (mongo `db.adminCommand('ping')`, `pg_isready`,
  `valkey-cli ping`): the containers' own healthchecks already run exactly
  these every 30s. Surfacing health (this plan) exposes their verdict; running
  them a second time from the probe is pure exec churn.
- **Backup content verification** (are the volumes really inside the restic
  snapshot): `restic-snapshot-alerts` proves backups succeed, not their content.
  Worth its own follow-up, unrelated to monitoring.
- Retiring `monit_cleanup` / the `container_health_probe_*` rules.

---

## Task 1: Probe script — `tier` label + `system_container_healthy`

**Files:**
- Modify: `ansible/plays/vars/default.yml` (new top-level key, near the other
  `docker_*`/service-level vars)
- Modify: `ansible/plays/roles/system_probe/templates/system_container_health.sh.j2:28-62`
- Modify: `ansible/plays/roles/system_probe/molecule/default/converge.yml`
- Create: `ansible/plays/roles/system_probe/molecule/default/files/backendtest/docker-compose.yml`
- Modify: `ansible/plays/roles/system_probe/molecule/default/verify.yml`

**Step 1: Create the molecule fixture (a backend service with a compose-derived name)**

`ansible/plays/roles/system_probe/molecule/default/files/backendtest/docker-compose.yml`:

```yaml
services:
  mongo:
    # ${COMPOSE_PROJECT_NAME} on purpose: the probe must resolve it to the
    # directory name, exactly as it does for shared.mongo.
    container_name: ${COMPOSE_PROJECT_NAME}.mongo
    image: mongo:9.0.8
```

**Step 2: Wire the fixture into converge**

In `molecule/default/converge.yml`, extend the `docker:` block (leave the rest
untouched):

```yaml
    docker:
      services:
        - dir: probetest
    # Backend-only services: watched by the probe, never exposed via DNS/ping.
    docker_backend_services:
      - dir: backendtest
```

**Step 3: Write the failing assertions**

Append to `molecule/default/verify.yml` (after the existing
"Assert fixture container resolved from compose file"):

```yaml
    - name: Assert backend service resolved from its compose file
      assert:
        that:
          - "'backendtest.mongo' in (container_script.content | b64decode)"

    - name: Assert both tiers are emitted
      assert:
        that:
          - >-
            'check_container "probetest.app" "probetest" "app"'
            in (container_script.content | b64decode)
          - >-
            'check_container "backendtest.mongo" "backendtest" "backend"'
            in (container_script.content | b64decode)

    - name: Assert the health metric is declared
      assert:
        that:
          - "'# TYPE system_container_healthy gauge' in (container_script.content | b64decode)"
```

**Step 4: Run molecule to verify it fails**

Run: `cd ansible/plays/roles/system_probe && molecule test --scenario-name default`
Expected: FAIL at "Assert backend service resolved from its compose file"
(`backendtest.mongo` absent) — confirms the test bites.

**Step 5: Add the backend list**

In `ansible/plays/vars/default.yml` (top level, not under `docker:` — `secrets.yml`
owns that key and clobbers it):

```yaml
# Container-health probe: services to watch that must NEVER be listed in
# `docker.services`. That list also creates Pi-hole DNS records, test_host.sh
# URLs and servyy-test /etc/hosts entries — all of which assume a public
# {dir}.{domain} endpoint. shared has no Traefik router and no name at all.
# Consumed only by system_probe/templates/system_container_health.sh.j2.
# See history/2026-11-17_shared-service-monitoring.md.
docker_backend_services:
  - dir: shared
```

**Step 6: Rewrite `check_container` (single inspect, two metrics, tier)**

Replace `templates/system_container_health.sh.j2:28-38` with:

```bash
check_container() {
  local container_name="$1" service_dir="$2" tier="$3"
  local state running health healthy
  # ONE inspect per container: a second call would double the docker exec churn
  # (history/2026-10-30_load-alert-tuning.md). Images without a healthcheck
  # have no .State.Health at all -> "none", which counts as healthy.
  state=$(docker container inspect "$container_name" \
    --format={% raw %}'{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'{% endraw %} 2>/dev/null) \
    || state="false none"
  running="${state%% *}"
  health="${state##* }"
  case "$health" in
    healthy|none) healthy=1 ;;
    *) healthy=0 ;;
  esac
  if [ "$running" = "true" ]; then
    printf 'system_container_running{name="%s",service="%s",tier="%s"} 1\n' "$container_name" "$service_dir" "$tier"
    # Emitted only while the container runs: a stopped container is already
    # covered by system_container_running 0, and reporting it here as well
    # would fire two alerts for one failure.
    printf 'system_container_healthy{name="%s",service="%s",tier="%s"} %s\n' "$container_name" "$service_dir" "$tier" "$healthy"
  else
    printf 'system_container_running{name="%s",service="%s",tier="%s"} 0\n' "$container_name" "$service_dir" "$tier"
    all_running=0
  fi
}
```

**Step 7: Iterate both lists in the payload builder**

Replace the two `# TYPE` lines and the loop at `:50-59` with:

```bash
  echo "# TYPE system_container_running gauge"
  echo "# TYPE system_container_healthy gauge"
{% set probe_services = (docker.services | rejectattr('manual', 'defined') | map('combine', {'tier': 'app'}) | list)
     + (docker_backend_services | default([]) | map('combine', {'tier': 'backend'}) | list) %}
{% for item in probe_services %}
{%   set project = item.dir %}
{%   set services = (lookup('file', (system_probe_docker_local_dir, item.dir, 'docker-compose.yml') | path_join ) | from_yaml)['services'] %}
{%   for svc in services | dict2items %}
{%     set raw_name = svc.value.container_name | default(project + '.' + svc.key) %}
{%     set container_name = raw_name | replace('${COMPOSE_PROJECT_NAME}', project) %}
  check_container "{{ container_name }}" "{{ project }}" "{{ item.tier }}"
{%   endfor %}
{% endfor %}
```

The trailing `all_running` log line and the curl PUT stay as they are —
`PUT` already replaces the whole job group, so the retired
`system_container_running{name,service}` series disappear on the first run.

**Step 8: Run molecule for both scenarios**

Run: `cd ansible/plays/roles/system_probe && molecule test`
Expected: `default` PASS (including the three new asserts) and `no-sink` PASS
(no monitor sink → probe not deployed; `docker_backend_services` is irrelevant
there).

**Step 9: Commit**

```bash
git add ansible/plays/vars/default.yml \
        ansible/plays/roles/system_probe/templates/system_container_health.sh.j2 \
        ansible/plays/roles/system_probe/molecule/default/converge.yml \
        ansible/plays/roles/system_probe/molecule/default/verify.yml \
        ansible/plays/roles/system_probe/molecule/default/files/backendtest/docker-compose.yml
git commit -m "feat(probe): watch backend services and surface container health

The shared data layer (mongo/valkey/postgres) was in no probe list, and the
probe only read .State.Running, so a container whose healthcheck fails stayed
green. Emit tier and a system_container_healthy gauge from the same inspect
(no extra docker exec), and read a backend-only list that skips the DNS/ping
side effects of docker.services."
```

---

## Task 2: Grafana alert rules

**Files:**
- Modify: `monitor/provisioning/alerting/alert-rules.yml` (group
  `container-health-alerts`, after `container_not_running`)

**Step 1: Add `backend_container_down`** (critical)

```yaml
      # CRITICAL, where a single app container is MEDIUM above: `shared` is the
      # data layer for leagues-finance, queen and dontforget — one dead
      # container takes all three down. Selects on tier, so future backend
      # services (a second db, a queue) are covered without touching this rule.
      - uid: backend_container_down
        title: Backend Container Down
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: system_container_running{tier="backend"}
              intervalMs: 1000
              maxDataPoints: 43200
              refId: A
          - refId: B
            queryType: ''
            datasourceUid: __expr__
            model:
              expression: A
              reducer: last
              refId: B
              type: reduce
          - refId: C
            queryType: ''
            datasourceUid: __expr__
            model:
              expression: B
              refId: C
              type: threshold
              conditions:
                - evaluator:
                    params: [0.5]
                    type: lt
        noDataState: OK
        execErrState: Error
        for: 1m
        annotations:
          summary: 'Backend container {{ $labels.name }} is not running'
          description: 'Container {{ $labels.name }} (service {{ $labels.service }}) is down. The shared data layer backs leagues-finance, queen and dontforget: expect errors in all of them until it is back. Check `docker logs {{ $labels.name }}` and the volume/mem_limit of that container.'
        labels:
          severity: critical
        missingSeriesEvalsToResolve: 3
        isPaused: false
```

**Step 2: Add `container_unhealthy`** (medium)

```yaml
      # MEDIUM: running, but its own healthcheck says unhealthy. This is the
      # gap the probe had until now: an unhealthy mongo keeps .State.Running
      # true, so nothing fired while every consumer's queries failed. `for: 10m`
      # because the shared containers need ~2.5min (5 x 30s) to be marked
      # unhealthy at all; shorter would page on a normal restart.
      - uid: container_unhealthy
        title: Container Unhealthy
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: prometheus
            model:
              expr: system_container_healthy
              intervalMs: 1000
              maxDataPoints: 43200
              refId: A
          - refId: B
            queryType: ''
            datasourceUid: __expr__
            model:
              expression: A
              reducer: last
              refId: B
              type: reduce
          - refId: C
            queryType: ''
            datasourceUid: __expr__
            model:
              expression: B
              refId: C
              type: threshold
              conditions:
                - evaluator:
                    params: [0.5]
                    type: lt
        noDataState: OK
        execErrState: Error
        for: 10m
        annotations:
          summary: 'Container {{ $labels.name }} is unhealthy'
          description: 'The container runs but its healthcheck has failed for 10 minutes (service {{ $labels.service }}). It keeps running while unhealthy - this is the difference between "up" and "answering". Run `docker inspect {{ $labels.name }}` and read State.Health.Log for the failing probe output.'
        labels:
          severity: medium
        missingSeriesEvalsToResolve: 3
        isPaused: false
```

**Step 3: Validate the YAML**

Run: `yamllint -c .yamllint.yml monitor/provisioning/alerting/alert-rules.yml`
Expected: no output. (`monitor/` is not in CI's yamllint scope — `yamllint` runs
on `ansible/plays` only — so this is a manual check.)

**Step 4: Commit**

```bash
git add monitor/provisioning/alerting/alert-rules.yml
git commit -m "feat(monitor): alert on backend containers down and unhealthy containers"
```

---

## Task 3: Docs, skills, history

**Files:**
- Modify: `.claude/skills/manage-service/SKILL.md` — the "Register the service
  in every list" section (it currently says `docker.services[]` drives probe,
  dns, host_ping, testing hosts) and the removal checklist.
- Modify: `.claude/skills/check-server-status/SKILL.md:23` — the enabled-services
  table entry for servy.
- Create: `history/2026-11-17_shared-service-monitoring.md`

**Step 1:** In `manage-service/SKILL.md`, after the `docker.services[]` bullet,
add:

```markdown
- `ansible/plays/vars/default.yml` → `docker_backend_services[]` — services the
  container-health probe must watch that must NOT be in `docker.services`
  (backend-only, no Traefik router: `shared`). `docker.services` also creates
  Pi-hole DNS, `test_host.sh` URLs and servyy-test `/etc/hosts`, so a
  backend-only service there produces a ping check that can never pass.
```

and in the removal checklist, next to the `docker.services[]` line:

```markdown
- [ ] `ansible/plays/vars/default.yml`: remove the `docker_backend_services[]`
  entry (the probe keeps alerting `backend_container_down` for a service nothing
  deploys)
```

**Step 2:** In `check-server-status/SKILL.md:23`, change the servy row entry
`shared (mongo/valkey/postgres)` to
`shared (mongo/valkey/postgres — backend-only, watched by the container-health
probe as tier="backend", no public name)`.

**Step 3:** Write `history/2026-11-17_shared-service-monitoring.md` with:
problem (shared in no probe list; `running` ≠ `healthy`; three apps behind one
data layer), what changed (the probe template + `docker_backend_services` + the
alert rules, the metric schema with the `tier` label), the verification evidence
from Task 4, rollback (`git revert` + `--tags system.probe` +
`docker restart monitor.grafana`; Pushgateway PUT replaces the group so no stale
series need deleting), and the out-of-scope list from this plan.

**Step 4: Commit**

```bash
git add .claude/skills/manage-service/SKILL.md .claude/skills/check-server-status/SKILL.md history/2026-11-17_shared-service-monitoring.md
git commit -m "docs: record backend-service monitoring in the skills and history"
```

---

## Task 4: Deploy and verify

**Step 1: Deploy the probe and the provisioning (both need the checkout)**

```bash
cd ansible
./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz
```

`--limit` takes the INVENTORY host (`servy.lehel.xyz`), not the SSH alias
`lehel.xyz` — the alias matches nothing and the run silently does nothing.
Expect `changed` on the repo-sync tasks and on the container-health template
task; every other probe task stays `ok` (their files do not change).

**Step 2: Reload Grafana** (file provisioning is read at start; `history/2026-08-15_pr63-system-probe-merge-deploy.md:51`)

```bash
ssh lehel.xyz "docker restart monitor.grafana"
```

**Step 3: Run the probe by hand instead of waiting for the 5-minute timer**

```bash
ssh lehel.xyz "~/.system-probes/system-container-health.sh"
```
Expected: `container-health all_running=1 probe_success=1 pushed=1`

**Step 4: Assert the new series exist**

```bash
ssh lehel.xyz 'curl -sf http://localhost:9091/metrics/job/system_container_health | grep -E "shared\.|tier="'
```
Expected: three `shared.*` series with `tier="backend"` and `running=1`, plus
`system_container_healthy 1` for each; every app container carries
`tier="app"`; no series without a `tier` label survives (PUT replaced them).
Adding `tier` re-keys every Grafana alert instance (instances are keyed by
labels), so expect the existing `container_not_running` instances to resolve and
re-appear as Normal — that is not a regression, but check them once.

**Step 5: Assert the alert rules loaded**

Grafana's own `/metrics` is off (`GF_METRICS_ENABLED=false` in
`templates/monitor/grafana.env.j2`, so there is no
`grafana_alerting_rule_group_rules` to grep), and the container publishes no
host port — query the provisioning API from inside the container with the
rendered admin password:

```bash
ssh lehel.xyz 'set -a; . /home/cda/servyy-container/monitor/grafana.env; set +a
AUTH=$(printf "admin:%s" "$GF_SECURITY_ADMIN_PASSWORD" | base64 -w0)
docker exec monitor.grafana wget -qO- --header="Authorization: Basic $AUTH" \
  http://localhost:3000/api/v1/provisioning/alert-rules \
  | grep -oE "\"uid\":\"(backend_container_down|container_unhealthy)\"" | sort -u'
```
Expected: two UIDs, one per new rule (the `container-health-alerts` group goes
from 4 rules to 6; it must NOT be empty — if it is, Grafana rejected the file
and the reason is in `docker logs monitor.grafana --since 5m`).

**Step 6: Prove the alert path actually fires (non-destructive)**

```bash
ssh lehel.xyz "docker stop shared.redis && sleep 90 && ~/.system-probes/system-container-health.sh; curl -sf http://localhost:9091/metrics/job/system_container_health | grep 'shared.redis'"
```
Expected: `running 0`, no `system_container_healthy` series for it. Then
`docker start shared.redis`, wait for the next push, and confirm the series
return to 1 (valkey is ephemeral by design — the queue retries, nothing is
lost). Do this BEFORE relying on the alert; do not skip it.

**Step 7: Confirm the alert resolved after the restart**

Check Grafana → Alerting → `container-health-alerts` for `backend_container_down`
state Normal, and that no `system_container_healthy 0` remains.

**Step 8: Report** — deploy result, the three series, the alert-rule count, and
the stop/start drill outcome in the history entry's verification section.

## Rollback

```bash
git revert <task1> <task2> && cd ansible && ./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz
ssh lehel.xyz "docker restart monitor.grafana"
```
The PUT push replaces the job group each run, so reverting the template drops the
`tier`/`system_container_healthy` series without manual cleanup; the old
`system_container_running{name,service}` series come back on the next push.

## Risks

- A mistyped `--format` in `check_container` would make every container report
  `running=0` → `containers_all_down` pages immediately. Mitigate: run the
  script by hand (Task 4 Step 3) and check `all_running=1` before considering the
  deploy done.
- `system_container_healthy` for images without a healthcheck is always 1, so
  the rule is silent for them by design (they cannot report unhealthy).
- The `for: 10m` on `container_unhealthy` is tuned to the 2.5-minute unhealthy
  detection of the 30s/5-retry healthchecks; if those intervals change, revisit
  it (`history/2026-10-30_load-alert-tuning.md`).
