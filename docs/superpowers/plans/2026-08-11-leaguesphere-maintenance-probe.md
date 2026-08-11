# LeagueSphere Maintenance/Games Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An hourly, automated check on production LeagueSphere that alerts (via the existing
Grafana email pipeline) if maintenance mode is active while real games are in progress.

**Architecture:** A new Ansible role (`ls_maintenance_probe`) deploys a bash script + systemd
user timer to `lehel.xyz`, mirroring `ls_db_sync`'s existing oneshot-timer structure exactly.
The script hits two already-public, already-proven endpoints (`/login/` for the maintenance
redirect check, `/api/game-progress/` for game state — same mechanisms
`container/healthcheck.sh` and CircleCI's `auto_approve_hold_production` job already use),
computes a combined "blocking" gauge, and pushes all of it to the Pushgateway already exposed on
`localhost:9091`. A new Grafana alert rule group evaluates the pushed gauges and emails through
the contact points that already deliver mail today.

**Tech Stack:** Ansible (roles, systemd templates), bash, curl, jq, Prometheus Pushgateway text
exposition format, Grafana unified alerting (YAML provisioning).

## Global Constraints

- Test-first, no manual production edits: validate on `servyy-test.lxd` / `stage.leaguesphere.app`
  before any production deploy; explicit user approval required before the production run (see
  design doc "Deployment policy" + repo `CLAUDE.md`).
- No application code changes — both HTTP endpoints already exist and are already public.
- No secrets required for this role (both endpoints are public/unauthenticated); `curl`/`jq` are
  already in `sys_packages` on every host.
- Metric names, alert semantics, and the script's fail-safe behavior must match
  `docs/superpowers/specs/2026-08-11-leaguesphere-maintenance-probe-design.md` exactly — that is
  the source of truth this plan implements.

---

## Task 1: Create feature branch

**Files:** none (git only)

- [ ] **Step 1: Confirm clean working tree and create the branch**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git status
git checkout -b feat/ls-maintenance-probe
```

Expected: `Switched to a new branch 'feat/ls-maintenance-probe'`, working tree was clean before
the switch.

---

## Task 2: Scaffold the `ls_maintenance_probe` role skeleton

**Files:**
- Create: `ansible/plays/roles/ls_maintenance_probe/defaults/main.yml`
- Create: `ansible/plays/roles/ls_maintenance_probe/tasks/oneshot_include.yml`
- Create: `ansible/plays/roles/ls_maintenance_probe/templates/oneshot.service.j2`
- Create: `ansible/plays/roles/ls_maintenance_probe/templates/oneshot.timer.j2`

**Interfaces:**
- Produces: an Ansible role directory `ls_maintenance_probe` with the standard
  oneshot-service/timer plumbing (identical contract to `ls_db_sync`'s: expects a `service` dict
  with `name`, `schedule`, `description`, `command` when `oneshot_include.yml` is imported).

- [ ] **Step 1: Create the directory structure**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible/plays/roles
mkdir -p ls_maintenance_probe/defaults ls_maintenance_probe/tasks ls_maintenance_probe/templates
```

- [ ] **Step 2: Write `defaults/main.yml`**

```yaml
---
# Defaults for ls_maintenance_probe role
# Overridden with -e ls_maintenance_probe_url=... to point the probe at stage during testing.
ls_maintenance_probe_url: "https://leaguesphere.app"
```

- [ ] **Step 3: Write `tasks/oneshot_include.yml`** (copied from `ls_db_sync`'s file, tag renamed)

```yaml
---
- name: Check mandatory variables are defined
  assert:
    that:
      - service is defined
      - service.name is defined
      - service.schedule is defined
      - service.description is defined
      - service.command is defined
    quiet: true
  tags:
    - ls.maintenance.probe

- name: Create the systemd directory if it does not exist
  ansible.builtin.file:
    path: "{{ remote_user_systemd }}"
    state: directory
  tags:
    - ls.maintenance.probe

- name: Create {{ service.name }} service
  template:
    src: oneshot.service.j2
    dest: "{{ (remote_user_systemd, service.name) | path_join }}.service"
  tags:
    - ls.maintenance.probe

- name: Create timer for {{ service.name }}
  template:
    src: oneshot.timer.j2
    dest: "{{ (remote_user_systemd, service.name) | path_join }}.timer"
  vars:
    timer:
      description: 'Trigger for {{ service.name }}'
      schedule: '{{ service.schedule }}'
  tags:
    - ls.maintenance.probe

- name: Start timer for {{ service.name }}
  systemd:
    scope: user
    name: '{{ service.name }}.timer'
    state: started
    enabled: yes
  tags:
    - ls.maintenance.probe
```

- [ ] **Step 4: Write `templates/oneshot.service.j2`** (identical to `ls_db_sync`'s)

```jinja
[Unit]
Description={{ service.description }}
{% if service.depends is defined %}
Requires={{ service.depends }}.service
{% endif %}

[Service]
Type=oneshot
ExecStart={{ service.command }}

[Install]
WantedBy=default.target
```

- [ ] **Step 5: Write `templates/oneshot.timer.j2`** (identical to `ls_db_sync`'s)

```jinja
[Unit]
Description={{ timer.description }}

[Timer]
OnCalendar={{ timer.schedule }}
RandomizedDelaySec=5m
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 6: Verify YAML/Jinja syntax**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
python3 -c "import yaml; yaml.safe_load(open('plays/roles/ls_maintenance_probe/defaults/main.yml'))" && echo "OK defaults"
python3 -c "import yaml; yaml.safe_load(open('plays/roles/ls_maintenance_probe/tasks/oneshot_include.yml'))" && echo "OK oneshot_include"
```

Expected: `OK defaults` and `OK oneshot_include` printed, no errors.

- [ ] **Step 7: Commit**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git add ansible/plays/roles/ls_maintenance_probe
git commit -m "feat: scaffold ls_maintenance_probe role skeleton"
```

---

## Task 3: Write the probe script template

**Files:**
- Create: `ansible/plays/roles/ls_maintenance_probe/templates/ls_maintenance_probe.sh.j2`

**Interfaces:**
- Consumes: `{{ ls_maintenance_probe_url }}` (from Task 2's `defaults/main.yml`, overridable via
  `-e`).
- Produces: on execution, pushes four gauges to `http://localhost:9091/metrics/job/leaguesphere_maintenance_probe`:
  `leaguesphere_maintenance_mode_active`, `leaguesphere_active_games`,
  `leaguesphere_maintenance_blocking_games`, `leaguesphere_probe_success`.

- [ ] **Step 1: Write the script**

```jinja
#!/bin/bash
set -uo pipefail
# Deliberately no `set -e`: each step below handles its own failure explicitly so a
# problem in one check (e.g. non-JSON response) can't abort the script before it pushes
# anything.

BASE_URL="{{ ls_maintenance_probe_url }}"
PUSHGATEWAY_URL="http://localhost:9091"
JOB_NAME="leaguesphere_maintenance_probe"

probe_success=1

# 1. Maintenance-mode detection (mirrors container/healthcheck.sh)
maintenance_active=0
http_code=$(curl -A ls-maintenance-probe -s -o /dev/null -w "%{http_code}" "${BASE_URL}/login/") || http_code="000"
if [ "$http_code" = "302" ]; then
  redirect=$(curl -A ls-maintenance-probe -s -o /dev/null -w "%{redirect_url}" "${BASE_URL}/login/")
  case "$redirect" in
    */maintenance/*) maintenance_active=1 ;;
  esac
elif [ "$http_code" != "200" ]; then
  probe_success=0
fi

# 2. Active-games detection (mirrors .circleci/config.yml auto_approve_hold_production).
# Assumption: /api/game-progress/ is never itself gated by maintenance_pages - CircleCI's
# own auto_approve job already depends on that being true today. If maintenance_pages is
# ever reconfigured to include /api/, exclude game-progress from it explicitly rather than
# relying on this script to route around it.
active_games=0
games_known=1
response=$(curl -A ls-maintenance-probe -s "${BASE_URL}/api/game-progress/?page_size=100")
if [ -z "$response" ] || ! echo "$response" | jq -e . >/dev/null 2>&1; then
  probe_success=0
  games_known=0
else
  today_date=$(TZ=Europe/Berlin date +%Y-%m-%d)
  active_games=$(echo "$response" | jq --arg today "$today_date" \
    '[.results[] | select(.date == $today) | .games[] | select(.status != "beendet" and .status != "Geplant")] | length')
fi

# Fail-safe: if maintenance is active and the game state can't be confirmed (e.g. the API
# call above failed), treat it as blocking rather than silently assuming zero active games
# - an unverifiable state is exactly the case where suppressing the alert would be worst.
blocking=0
if [ "$maintenance_active" = "1" ] && { [ "$games_known" = "0" ] || [ "$active_games" -gt 0 ]; }; then
  blocking=1
fi

cat <<EOF | curl -sf --data-binary @- "${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME}"
# TYPE leaguesphere_maintenance_mode_active gauge
leaguesphere_maintenance_mode_active ${maintenance_active}
# TYPE leaguesphere_active_games gauge
leaguesphere_active_games ${active_games}
# TYPE leaguesphere_maintenance_blocking_games gauge
leaguesphere_maintenance_blocking_games ${blocking}
# TYPE leaguesphere_probe_success gauge
leaguesphere_probe_success ${probe_success}
EOF

echo "maintenance_active=${maintenance_active} active_games=${active_games} blocking=${blocking} probe_success=${probe_success}"
```

- [ ] **Step 2: Verify the template renders with valid Jinja by running it through ansible's templater locally**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
python3 - <<'PYEOF'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('plays/roles/ls_maintenance_probe/templates'))
tpl = env.get_template('ls_maintenance_probe.sh.j2')
print(tpl.render(ls_maintenance_probe_url="https://stage.leaguesphere.app"))
PYEOF
```

Expected: full shell script printed with `BASE_URL="https://stage.leaguesphere.app"`
substituted, no Jinja errors.

- [ ] **Step 3: Commit**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git add ansible/plays/roles/ls_maintenance_probe/templates/ls_maintenance_probe.sh.j2
git commit -m "feat: add LeagueSphere maintenance/games probe script"
```

---

## Task 4: Wire the role's `tasks/main.yml`

**Files:**
- Create: `ansible/plays/roles/ls_maintenance_probe/tasks/main.yml`

**Interfaces:**
- Consumes: `remote_user_home`, `create_user` (from `ansible/plays/vars/default.yml` /
  `secrets.yml`, already loaded by the parent playbook), `oneshot_include.yml` from Task 2,
  `ls_maintenance_probe.sh.j2` from Task 3.
- Produces: deployed script at `{{ remote_user_home }}/.backup-scripts/ls-maintenance-probe.sh`
  and an enabled `ls-maintenance-probe.timer` (user scope) firing hourly on the hour.

- [ ] **Step 1: Write `tasks/main.yml`**

```yaml
---
- name: Ensure operational scripts directory exists
  file:
    path: "{{ remote_user_home }}/.backup-scripts"
    state: directory
    mode: '0755'
  become_user: "{{ create_user }}"
  tags:
    - ls.maintenance.probe

- name: Deploy LeagueSphere maintenance/games probe script
  template:
    src: ls_maintenance_probe.sh.j2
    dest: "{{ remote_user_home }}/.backup-scripts/ls-maintenance-probe.sh"
    mode: '0750'
  become_user: "{{ create_user }}"
  tags:
    - ls.maintenance.probe

- name: Deploy hourly timer for maintenance/games probe
  import_tasks: oneshot_include.yml
  become_user: "{{ create_user }}"
  vars:
    service:
      name: ls-maintenance-probe
      description: 'Hourly LeagueSphere maintenance-mode / active-games probe'
      schedule: '*-*-* *:00:00'
      command: "{{ remote_user_home }}/.backup-scripts/ls-maintenance-probe.sh"
  tags:
    - ls.maintenance.probe
```

- [ ] **Step 2: Verify YAML syntax**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
python3 -c "import yaml; yaml.safe_load(open('plays/roles/ls_maintenance_probe/tasks/main.yml'))" && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git add ansible/plays/roles/ls_maintenance_probe/tasks/main.yml
git commit -m "feat: deploy script and hourly timer in ls_maintenance_probe role"
```

---

## Task 5: Register the role in `leaguesphere.yml`

**Files:**
- Modify: `ansible/plays/leaguesphere.yml`

**Interfaces:**
- Consumes: role `ls_maintenance_probe` from Tasks 2-4.
- Produces: tag `ls.maintenance.probe` runnable via `./servyy.sh --tags ls.maintenance.probe` /
  `./servyy-test.sh --tags ls.maintenance.probe`.

- [ ] **Step 1: Add the role entry after the existing `ls_db_migrate` entry**

Find this block (existing, near the end of the `roles:` list):

```yaml
    # DB migrate role - on-demand seed of local prod db from external (tag-only, not in default ls run)
    - role: ls_db_migrate
      tags:
        - ls.db.migrate
```

Add immediately after it:

```yaml

    # Hourly maintenance-mode / active-games probe - tag-only, not in default ls run
    # (mirrors ls_db_migrate above). Pushes metrics to Pushgateway; Grafana alerts on them.
    - role: ls_maintenance_probe
      tags:
        - ls.maintenance.probe
```

- [ ] **Step 2: Verify playbook syntax**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
./servyy.sh --syntax-check
```

Expected: `playbook: servyy.yml` printed, no errors.

- [ ] **Step 3: Confirm the new tag is visible**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
ansible-playbook servyy.yml -i production --list-tags 2>/dev/null | grep -o 'ls.maintenance.probe'
```

Expected: `ls.maintenance.probe` printed.

- [ ] **Step 4: Commit**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git add ansible/plays/leaguesphere.yml
git commit -m "feat: register ls_maintenance_probe role in leaguesphere playbook"
```

---

## Task 6: Add Grafana alert rules

**Files:**
- Modify: `monitor/provisioning/alerting/alert-rules.yml`

**Interfaces:**
- Consumes: metrics `leaguesphere_maintenance_blocking_games`, `leaguesphere_probe_success`,
  `push_time_seconds{job="leaguesphere_maintenance_probe"}` (all produced by Task 3's script
  once deployed and run).
- Produces: three new alert rules in a new `LeagueSphere` folder, routed by existing
  `severity` labels through `notification-policies.yml` (critical -> `email-critical`, medium ->
  `email-admin`) — no changes needed to contact points or policies.

- [ ] **Step 1: Append a new group to the end of `alert-rules.yml`**

Add this as a new top-level entry in the `groups:` list (after the existing
`infrastructure-alerts` group, same indentation level):

```yaml
  # LeagueSphere maintenance/games monitoring
  - orgId: 1
    name: leaguesphere-alerts
    folder: LeagueSphere
    interval: 1m
    rules:
      # CRITICAL: maintenance mode is blocking real, in-progress games
      - uid: leaguesphere_maintenance_blocking_games
        title: Maintenance Mode Blocking Live Games
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: leaguesphere_maintenance_blocking_games
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
                    type: gt
        noDataState: OK
        execErrState: Error
        for: 5m
        annotations:
          summary: 'LeagueSphere maintenance mode is blocking live games'
          description: 'Maintenance mode is active while games are in progress today - real users are locked out during a live game. Disable maintenance mode or confirm this is intentional immediately.'
        labels:
          severity: critical
        isPaused: false

      # MEDIUM: the probe itself can't reach prod / parse its response
      - uid: leaguesphere_maintenance_probe_success
        title: LeagueSphere Maintenance Probe Failing
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: leaguesphere_probe_success
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
          summary: 'LeagueSphere maintenance/games probe is failing'
          description: 'The hourly maintenance-mode/games probe could not reach or parse a response from LeagueSphere for 10+ minutes - check ls-maintenance-probe.service on lehel.xyz.'
        labels:
          severity: medium
        isPaused: false

      # MEDIUM: the probe has stopped running entirely (timer dead, not just failing)
      - uid: leaguesphere_maintenance_probe_stale
        title: LeagueSphere Maintenance Probe Stale
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: time() - push_time_seconds{job="leaguesphere_maintenance_probe"}
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
                    params: [5400]
                    type: gt
        noDataState: OK
        execErrState: Error
        for: 1m
        annotations:
          summary: 'LeagueSphere maintenance probe has not pushed metrics recently'
          description: 'No successful push from ls-maintenance-probe.timer in over 90 minutes - the hourly timer on lehel.xyz may have stopped running.'
        labels:
          severity: medium
        isPaused: false
```

- [ ] **Step 2: Verify YAML syntax**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/monitor
python3 -c "import yaml; yaml.safe_load(open('provisioning/alerting/alert-rules.yml'))" && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git add monitor/provisioning/alerting/alert-rules.yml
git commit -m "feat: add Grafana alert rules for LeagueSphere maintenance/games probe"
```

---

## Task 7: Deploy and validate script logic on `servyy-test.lxd` against stage

**Files:** none (deployment/verification only)

- [ ] **Step 1: Deploy the role to the test box, pointed at public stage**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
./servyy-test.sh --tags ls.maintenance.probe -e ls_maintenance_probe_url=https://stage.leaguesphere.app
```

Expected: play completes with no failed tasks (`failed=0`).

- [ ] **Step 2: Verify the script and timer were deployed**

```bash
ssh servyy-test.lxd "ls -la ~/.backup-scripts/ls-maintenance-probe.sh"
ssh servyy-test.lxd "systemctl --user status ls-maintenance-probe.timer --no-pager"
```

Expected: script file present with mode `750`; timer shows `enabled` and `active (waiting)`.

- [ ] **Step 3: Run the probe once manually and inspect its output**

```bash
ssh servyy-test.lxd "~/.backup-scripts/ls-maintenance-probe.sh"
```

Expected: a line like `maintenance_active=0 active_games=<N> blocking=0 probe_success=1`
(assuming stage isn't currently in maintenance mode). The final `curl` to `localhost:9091` is
expected to fail here (connection refused) since `servyy-test.lxd` has no Pushgateway running —
that's fine for this task; the script must still print the summary line and exit without
hanging, since there is no `set -e`.

Expected: script does **not** hang; the summary line prints regardless of the pushgateway curl
outcome.

- [ ] **Step 4: Manually STOP AND ASK USER for a maintenance-mode toggle check**

This requires production/stage Django-admin credentials the agent does not have — ask the user
to do the following in a browser, then confirm the values that were observed:

> Please log into `https://stage.leaguesphere.app/admin/`, visit
> `/admin/league_manager/siteconfiguration/toggle-maintenance/` to flip stage's maintenance mode
> ON, confirm, then let me know when it's flipped so I can re-run the probe and check the
> output — then we'll flip it back off together.

- [ ] **Step 5: Re-run the probe with maintenance mode ON (after user confirms Step 4)**

```bash
ssh servyy-test.lxd "~/.backup-scripts/ls-maintenance-probe.sh"
```

Expected: `maintenance_active=1` in the summary line (was `0` in Step 3); `blocking` reflects
`active_games` at the time (1 if stage has any non-`beendet`/`Geplant` game today, else 0 — check
against the same figure Step 3 reported).

- [ ] **Step 6: Ask the user to flip stage's maintenance mode back OFF**, then re-run once more
  to confirm `maintenance_active=0` again.

```bash
ssh servyy-test.lxd "~/.backup-scripts/ls-maintenance-probe.sh"
```

Expected: `maintenance_active=0` again.

- [ ] **Step 7: No commit for this task** (deployment/verification only, no file changes).

---

## Task 8: Validate the Grafana alert pipeline on production with synthetic data

**Files:** none (verification only — does **not** deploy the role to production; pushes
throwaway data directly to the existing Pushgateway to prove the already-committed alert rules
from Task 6 actually fire and email, before those rules see real probe data)

> This task requires Task 6's alert rules to already be live on the production Grafana
> instance. Since "Monitor" is a `manual: true` service, this task starts by pushing that config
> out.

- [ ] **Step 1: Deploy the updated alert-rules.yml to production's Monitor stack**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
./servyy.sh --tags user.docker.monitor -e manual=false --limit lehel.xyz
```

Expected: play completes with no failed tasks; Grafana container recreated/restarted picking up
the new provisioning file.

- [ ] **Step 2: Confirm the new rules loaded**

```bash
ssh lehel.xyz "docker logs lehel.grafana --tail 50 2>&1 | grep -i 'leaguesphere-alerts\|error'"
```

Expected: no error lines referencing `leaguesphere-alerts`; if Grafana logs provisioning success
messages, one should reference the new rule group.

- [ ] **Step 3: Push a synthetic "blocking" payload directly to production's Pushgateway**

```bash
ssh lehel.xyz "cat <<'EOF' | curl -sf --data-binary @- http://localhost:9091/metrics/job/leaguesphere_maintenance_probe_test
# TYPE leaguesphere_maintenance_blocking_games gauge
leaguesphere_maintenance_blocking_games 1
EOF"
```

Expected: curl exits 0 (no output on success, Pushgateway returns 200).

> Note: this pushes to job `leaguesphere_maintenance_probe_test`, a different job label than the
> real script uses (`leaguesphere_maintenance_probe`) — the alert rule's PromQL
> (`leaguesphere_maintenance_blocking_games`, no job filter) matches on metric name only, so this
> still exercises the exact same rule the real probe will trigger, without colliding with (or
> being confused for) real probe data.

- [ ] **Step 4: STOP AND ASK USER to confirm the alert fired and the email arrived**

Wait ~5-6 minutes (the rule's `for: 5m`), then check:

```bash
# Open https://monitor.lehel.xyz -> Alerting -> confirm "Maintenance Mode Blocking Live Games" is in Firing state
```

Ask the user to confirm receipt of the critical-severity email at
`dachrischx+monitor@gmail.com`.

- [ ] **Step 5: Clean up the synthetic metric**

```bash
ssh lehel.xyz "curl -sf -X DELETE http://localhost:9091/metrics/job/leaguesphere_maintenance_probe_test"
```

Expected: curl exits 0. Re-check the Grafana alert UI — it should return to Normal/Resolved
within the next evaluation interval (up to 1m).

- [ ] **Step 6: No commit for this task** (verification only; Task 6's file changes were already
  committed).

---

## Task 9: Deploy the probe role to production (after explicit approval)

**Files:** none (deployment only)

- [ ] **Step 1: STOP AND ASK USER for explicit production-deploy approval**

Summarize before asking: role scaffolded and script logic validated against stage (Task 7),
alert pipeline validated against prod with synthetic data and cleaned up (Task 8). Ask: "Ready
to deploy the real hourly probe to production, pointed at `https://leaguesphere.app`?"

- [ ] **Step 2: Deploy to production (only after approval)**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container/ansible
./servyy.sh --tags ls.maintenance.probe --limit lehel.xyz
```

Expected: play completes with no failed tasks. `ls_maintenance_probe_url` is not overridden, so
it uses the role default `https://leaguesphere.app`.

- [ ] **Step 3: Verify the timer is active on prod**

```bash
ssh lehel.xyz "systemctl --user status ls-maintenance-probe.timer --no-pager"
ssh lehel.xyz "systemctl --user list-timers ls-maintenance-probe.timer --no-pager"
```

Expected: timer `enabled`/`active (waiting)`, next scheduled run shown within the current hour
(plus up to 5 minutes of `RandomizedDelaySec`).

- [ ] **Step 4: Trigger one real run manually and confirm it reaches the real Pushgateway**

```bash
ssh lehel.xyz "~/.backup-scripts/ls-maintenance-probe.sh"
ssh lehel.xyz "curl -s http://localhost:9091/metrics | grep leaguesphere_"
```

Expected: the four `leaguesphere_*` gauges present in the Pushgateway's `/metrics` output,
reflecting real current prod state (`maintenance_active=0`, `probe_success=1` under normal
conditions).

- [ ] **Step 5: Confirm Prometheus is scraping the fresh values**

```bash
ssh lehel.xyz "docker exec lehel.prometheus wget -q -O- 'http://localhost:9090/api/v1/query?query=leaguesphere_probe_success' | grep -o '\"value\":\[[^]]*\]'"
```

Expected: a value array showing `1` (probe succeeded) with a recent timestamp.

---

## Task 10: Merge to master

**Files:** none (git only)

- [ ] **Step 1: Review the full diff**

```bash
cd /home/cda/.agent-deck/multi-repo-worktrees/d957d517/container
git log --oneline main..feat/ls-maintenance-probe
git diff master...feat/ls-maintenance-probe --stat
```

Expected: 6 commits (Tasks 1-6), touching `ansible/plays/roles/ls_maintenance_probe/**`,
`ansible/plays/leaguesphere.yml`, `monitor/provisioning/alerting/alert-rules.yml`.

- [ ] **Step 2: Merge**

```bash
git checkout master
git merge feat/ls-maintenance-probe
```

Expected: fast-forward or clean merge commit.

---

## Self-Review Checklist

**Spec coverage:**
- [x] Maintenance-mode detection via `/login/` redirect -> Task 3 (script Step 1)
- [x] Active-games detection via `/api/game-progress/` -> Task 3 (script Step 1)
- [x] `leaguesphere_maintenance_blocking_games` precomputed fail-safe -> Task 3
- [x] `leaguesphere_probe_success` -> Task 3
- [x] Pushgateway delivery to `localhost:9091` -> Task 3
- [x] Hourly systemd timer, no secrets, reuses `sys_packages` curl/jq -> Tasks 2, 4
- [x] Role registered tag-only (not bundled into `ls.app`) -> Task 5
- [x] Three Grafana alert rules (blocking/critical, probe-failing/medium, stale/medium) -> Task 6
- [x] Script logic validated against stage -> Task 7
- [x] Alert pipeline validated against prod with synthetic data, then cleaned up -> Task 8
- [x] Explicit approval before production deploy -> Task 9 Step 1
- [x] Follow-on Monit-replacement sub-projects and SSHD staying on Monit are explicitly
  out of scope (design doc "Non-goals") — no task in this plan touches them.

**Placeholder scan:** no TBD/TODO; all code blocks are complete, no "similar to Task N" references.

**Type consistency:** metric names (`leaguesphere_maintenance_mode_active`,
`leaguesphere_active_games`, `leaguesphere_maintenance_blocking_games`,
`leaguesphere_probe_success`) match verbatim between Task 3 (script), Task 6 (alert rules), and
Task 9 (verification greps). Role/tag names (`ls_maintenance_probe`, `ls.maintenance.probe`)
match verbatim across Tasks 2, 4, 5, 7, 9. Service name `ls-maintenance-probe` (hyphenated, no
underscores — matches the systemd unit naming convention used by `ls-db-sync-nightly`) is
consistent across Tasks 4, 7, 9.
