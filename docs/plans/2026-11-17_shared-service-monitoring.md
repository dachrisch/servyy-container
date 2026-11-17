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
6. **No double paging, in both directions.** `system_container_running` and
   `system_container_healthy` are shared with the existing app rules, so those are
   narrowed to `tier!="backend"` and two CRITICAL backend mirrors cover the data
   layer. A stopped container drops out of the healthy series entirely
   (`system_container_healthy` is emitted only while running), so "down" and
   "unhealthy" can never both fire for it.
7. **`for:` must span a push gap.** The probe pushes every 5 min with up to 5 min
   of `RandomizedDelaySec`, so consecutive pushes are 0–10 min apart, and
   Pushgateway keeps serving the last pushed value until the next PUT. A `for:`
   below 10 min therefore lets a single bad push page; 10 min covers the typical
   gap and absorbs one bad push unless the next one is also ~10 min late. The
   price is time-to-page: a real stop pages 11–20 min later. Shorter is not
   defensible without a second confirmation source.
8. **`system_container_healthy` counts `starting` as unhealthy.** The Docker
   healthcheck has not passed yet, so "answering" is not established; the 10 min
   `for:` absorbs normal restart windows (the shared healthchecks retry
   5 × 30s).

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
- **Lowering `container_health_probe_stale`'s 90-minute threshold**: this change
  makes the probe the only critical path for the data layer, while the probe's own
  death is only signalled at MEDIUM after 90 minutes, and
  `container_health_probe_failure` reads a series that vanishes with the job.
  Worse, if the timer dies while a `0` sits in Pushgateway,
  `backend_container_not_running` fires forever and can never resolve. A ~30 min
  threshold (3 pushes of slack) is a one-liner worth doing soon.
- **Crash-looping backend container**: each brief stop makes the healthy series
  vanish, and `noDataState: OK` resets the `for` clock, while `running`
  alternates 0/1 — so neither rule reaches 10 min even though every consumer is
  down. A cAdvisor rule on
  `changes(container_start_time_seconds{name=~"shared\\..*"}[30m])` would close
  it with no probe cost. (A *paused* container is likewise invisible:
  `running=1`, health frozen.)
- **`container_not_running` still uses `for: 2m`**, shorter than a full push gap
  (5 min + up to 5 min jitter). The probe's inspect retry removes the common
  single-hiccup case, but one wrong *push* can still fire it; aligning it to
  `10m` like the two new rules is the obvious follow-up. Left alone here to keep
  the diff to the new signal.
- **`containers_all_down` now averages over a bigger population**: the three
  `shared.*` series join `avg(system_container_running)` (32 → 35 series as the
  probe stood at deploy time), so its "majority down" threshold shifts slightly.
  Intended — the backend containers
  belong in the host-wide signal — but worth knowing when reading the number.
  It also has no `missingSeriesEvalsToResolve`, unlike `container_not_running`;
  pre-existing asymmetry, out of scope here.
- **A staleness rule for the container-health job itself** (`absent(system_container_running)`):
  `container_health_probe_failure` only reads a series that disappears with the
  job, so a dead timer is caught only by `container_health_probe_stale`'s own
  logic. This becomes more important once the probe is the critical signal for
  the data layer; still out of scope here.
- **Deduplicating a dir listed in both `docker.services` and
  `docker_backend_services`**: it would emit two series (different `tier`) and two
  inspects per container. Guarded by a comment and the Task 3 skill note rather
  than a `unique` assert.
- **Host-gating `docker_backend_services`** (like `leaguesphere_enabled` gates the
  db entries in `roles/system_probe/defaults/main.yml`): safe today because the
  probe only deploys where `monitor` is enabled, and no such host lacks
  `shared`. Enabling `monitor` on a host without `shared` would fire a CRITICAL
  for a service that host never runs.
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
          # The asserts below are what actually pin the emission path: the
          # `# TYPE` line above alone stays green if both printfs (or the
          # --format) are broken, and a broken --format makes every container
          # report running=0 -> containers_all_down pages on deploy.
          - "'system_container_healthy{name=\"%s\",service=\"%s\",tier=\"%s\"}' in (container_script.content | b64decode)"
          - "'system_container_running{name=\"%s\",service=\"%s\",tier=\"%s\"}' in (container_script.content | b64decode)"
          # Concatenated on purpose: a literal `{{` inside a conditional string
          # is itself parsed as an embedded template — it errors on ansible-core
          # 2.20 (`'in <string>' requires string as left operand, not
          # UndefinedMarker`), and `{% raw %}` is a hard syntax error inside a
          # `that:` expression, not a workaround.
          - "('{' ~ '{if .State.Health}' ~ '}') in (container_script.content | b64decode)"
          # Distinctive fragment of the running-branch printf only: the
          # `system_container_running{name="%s",…}` needle above also matches the
          # stopped-branch printf, so deleting just one of the two stayed green.
          - "'tier=\"%s\"} 1' in (container_script.content | b64decode)"
          - "'.State.Health.Status' in (container_script.content | b64decode)"
          # The healthcheck-less fallback: without it every image that declares
          # no healthcheck parses as unhealthy, and container_unhealthy fires for
          # all of them.
          - "('{' ~ '{else}}none{' ~ '{end}}') in (container_script.content | b64decode)"
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
  # One string, used by the first attempt and the retry: two inline copies could
  # silently diverge, and the health branch is what decides healthy vs
  # unhealthy. Images without a healthcheck have no .State.Health at all ->
  # "none", which counts as healthy.
  local fmt={% raw %}'{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'{% endraw %}
  # ONE inspect per container in the steady state (history/2026-10-30_load-alert-tuning.md).
  # The SECOND attempt only runs on failure: pushes are 5-10 min apart (timer
  # *:0/5 + RandomizedDelaySec=5m), so without the retry one dockerd hiccup keeps
  # a healthy container at 0 until the next push and fires container_not_running
  # (for: 2m) on a phantom.
  state=$(docker container inspect "$container_name" --format="$fmt" 2>/dev/null) || {
    sleep 2
    state=$(docker container inspect "$container_name" --format="$fmt" 2>/dev/null)
  } || state="false none"
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
Expected: `default` PASS (including the new asserts — six needles in the emission
task, plus the fixture/tier/TYPE ones) and `no-sink` PASS
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

**Step 1: Scope the existing per-container rule to app containers**

`system_container_running` now also carries the backend containers, so the
untouched `container_not_running` rule would fire a MEDIUM *and* the new
CRITICAL for the same stopped `shared.mongo` — one failure, two pages. Narrow it
(only the expression changes; leave `for`, annotations and everything else
alone), in `monitor/provisioning/alerting/alert-rules.yml` around `:1876`:

```yaml
            model:
              # Backend containers have their own CRITICAL rules below
              # (backend_container_not_running / backend_container_unhealthy): a
              # data-layer outage must not page twice for one container.
              expr: system_container_running{tier!="backend"}
```

**Step 2: Add `backend_container_not_running`** (critical)

```yaml
      # CRITICAL, where a single app container is MEDIUM above: `shared` is the
      # data layer for leagues-finance, queen and dontforget — one dead
      # container takes all three down. Selects on tier, so future backend
      # services (a second db, a queue) are covered without touching this rule.
      - uid: backend_container_not_running
        title: Backend Container Not Running
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
        # 10m, not 1m: the probe pushes every 5 min with up to 5 min of
        # RandomizedDelaySec, so consecutive pushes are 0-10 min apart - and
        # Pushgateway keeps serving the last pushed value until the next PUT, so
        # a phantom 0 stays visible for up to that whole gap. 10m covers the
        # typical gap and absorbs one bad push unless the next one is also ~10
        # min late (the retry handles a failed inspect, not a wrong push). Cost:
        # a real stop pages 11-20 min later (0-10 min to the next push, then the
        # 10 min of `for`).
        for: 10m
        annotations:
          summary: 'Backend container {{ $labels.name }} is not running'
          description: 'Container {{ $labels.name }} (service {{ $labels.service }}) is not running. The shared data layer backs leagues-finance, queen and dontforget: expect errors in all of them until it is back. Check `docker logs --tail 50 {{ $labels.name }}` for the exit reason and `docker inspect {{ $labels.name }}` for the exit code / OOMKilled flag.'
        labels:
          severity: critical
        missingSeriesEvalsToResolve: 3
        isPaused: false
```

**Step 3: Add `container_unhealthy`** (medium, app tier only)

```yaml
      # MEDIUM: running, but its own healthcheck says unhealthy. This is the
      # gap the probe had until now: an unhealthy mongo keeps .State.Running
      # true, so nothing fired while every consumer's queries failed. `for: 10m`
      # because the shared containers need ~2.5min (5 x 30s) to be marked
      # unhealthy at all; shorter would page on a normal restart. Scoped to the
      # app tier: the data layer's equivalent is CRITICAL (next step).
      # from: 300s, NOT 900: a range query keeps returning the last sample for
      # the whole window, so a container seen unhealthy and then STOPPED would
      # still read "unhealthy" for 15 min - a guaranteed duplicate page next to
      # the not-running rule (and a false "the container runs" in the text).
      - uid: container_unhealthy
        title: Container Unhealthy
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: system_container_healthy{tier!="backend"}
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

**Step 4: Add `backend_container_unhealthy`** (critical) and renumber below

Same shape, placed directly after `container_unhealthy`:

```yaml
      # CRITICAL, mirroring the down / not-running pairing above: the shared
      # healthchecks are protocol level (mongosh ping, valkey-cli ping,
      # pg_isready), so "unhealthy for 10 minutes" means the data layer is not
      # answering for leagues-finance, queen and dontforget - the same blast
      # radius as a stopped container, hence the same severity. The app-tier
      # equivalent above stays MEDIUM: a single app that is up but degraded is
      # not host-fatal.
      - uid: backend_container_unhealthy
        title: Backend Container Unhealthy
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: system_container_healthy{tier="backend"}
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
          summary: 'Backend container {{ $labels.name }} is unhealthy'
          description: 'The shared data layer (service {{ $labels.service }}) has been answering its healthcheck as unhealthy for 10+ minutes, so leagues-finance, queen and dontforget are erroring against it. It is still running - this is "up but not answering". Run `docker inspect {{ $labels.name }}` and read State.Health.Log; the container keeps running while unhealthy, so a restart is the usual fix.'
        labels:
          severity: critical
        missingSeriesEvalsToResolve: 3
        isPaused: false
```

Do NOT put `--format '{{json .State.Health.Log}}'` in an annotation — Grafana
templates those braces and the text renders broken.

**Step 5: Validate the YAML**

Run: `yamllint -c .yamllint.yml monitor/provisioning/alerting/alert-rules.yml`
Expected: exit 0 with ~38 `line-length` warnings — the file has 34 at baseline
because every rule carries one long single-quoted `description`, and the new
ones add more of the same shape. Do not fold only the new ones into `>-`
block scalars: that makes them the only rules in the file that look different.
CI does not lint `monitor/` (`yamllint` runs on `ansible/plays` only).

Also assert the group holds **7** rules in this order: `container_not_running`,
`backend_container_not_running`, `container_unhealthy`,
`backend_container_unhealthy`, `containers_all_down`,
`container_health_probe_failure`, `container_health_probe_stale`; and that no
`backend_container_down` string survives anywhere (`grep -rn`).

**Step 6: Commit**

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
- Modify: `ansible/plays/roles/system_probe/defaults/main.yml` — its header calls
  itself the scoping summary but documents only `system_probe_docker_local_dir`
  in the container-health section; it must point at `docker_backend_services`
  (in `plays/vars/default.yml`) as the second list the template consumes.
- Create: `history/2026-11-17_shared-service-monitoring.md` — EXACTLY that
  filename: `ansible/plays/vars/default.yml` and the probe template already
  reference it, and a different name leaves two dangling links.

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
  | grep -oE "\"uid\":\"(backend_container_not_running|backend_container_unhealthy|container_unhealthy)\"" | sort -u'
```
Expected: three UIDs (the `container-health-alerts` group goes from 4 rules to 7;
it must NOT be empty — if it is, Grafana rejected the file and the reason is in
`docker logs monitor.grafana --since 5m`).

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
- One bad push must never page: the probe interval is 5 min with up to 5 min of
  `RandomizedDelaySec`, which is why both new rules use `for: 10m` and why the
  probe retries a failed `inspect` once. Tightening `for:` below ~10 min
  reintroduces phantom criticals.
- The molecule asserts pin the two `printf` format strings, the running-branch
  discriminator, the health-status field and the `else}}none` fallback precisely
  because a broken `--format` renders green everywhere else and only shows up in
  production (`containers_all_down`, or `container_unhealthy` for every
  healthcheck-less container). Mutation-tested: each of those five mutations
  fails the assert.
- The retry doubles the exposure of a *hung* (not failing) `inspect`, and the
  `system-container-health` unit has no `TimeoutStartSec` (`Type=oneshot`,
  `TimeoutStartUSec=infinity`). Worst case measured on the current 35 containers
  when every inspect fails: ~74 s, against a 5-minute timer, so no overlap today.
  Revisit if the host grows past ~90 containers or if dockerd can hang instead of
  erroring.
- Molecule never EXECUTES the rendered script — it asserts on its text. The
  needles are mutation-tested (each of the eight now fails a specific mutant) but
  they pin strings, not behaviour: a refactor that moves the printfs into a
  helper breaks them, and a logic change that keeps the strings passes. A small
  stub-`docker` bash test would cover behaviour; out of scope for this task, and
  the deploy-time drill in Task 4 is the behavioural check that matters.
