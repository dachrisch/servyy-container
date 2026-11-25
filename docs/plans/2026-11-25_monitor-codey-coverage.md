# Monitor codey coverage + notification tuning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop alert-email storms and make codey's host, containers and logs observable without adding a new cross-host network route.

**Architecture:** Keep the one compose project / two-profile split. Add a second, local Prometheus stack to the `ui` profile on codey with distinct container names; a second Grafana datasource and a focused rule file use it. Route notifications by severity and suppress resolve messages. Reuse the existing authenticated Loki route for codey's logs and the container-health probe.

**Tech Stack:** Docker Compose profiles, Prometheus scrape config, Grafana file provisioning, Ansible roles (`docker_service`, `monitor_reload`, `system_probe`), Molecule, pytest/unittest.

---

### Task 1: Notification tuning (TDD)

**Files:**
- Test: `ansible/tests/monitor_alerts/test_notification_tuning.py`
- Modify: `monitor/provisioning/alerting/notification-policies.yml`
- Modify: `monitor/provisioning/alerting/contact-points.yml`

**Step 1** Write tests asserting: root `group_by == ['severity']`; each severity route repeat is critical `1h`, high `4h`, medium `12h`; both contact points have `disableResolveMessage: true`; all 65+ rule UIDs in `alert-rules.yml` are unique.

**Step 2** Run `python -m unittest discover -s ansible/tests/monitor_alerts -p 'test_*.py' -v` — expect FAIL on group_by.

**Step 3** Edit the two YAML files to satisfy the tests.

**Step 4** Re-run tests — expect PASS.

**Step 5** Commit: `fix(monitor): batch alert emails by severity and stop resolve spam`

### Task 2: Codey local collector compose services

**Files:**
- Create: `monitor/prometheus-codey.yml`
- Modify: `monitor/docker-compose.yml`
- Modify: `ansible/plays/vars/default.yml` (`world_readable_paths_by_service.monitor`)
- Test: `ansible/tests/monitor_codey/test_compose.py`

**Step 1** Write tests parsing `monitor/docker-compose.yml`: services `prometheus-codey`, `node-exporter-codey`, `cadvisor-codey`, `pushgateway-codey`, `pushgateway-bridge-codey`, `promtail-codey` exist, all carry profile `ui`, all container names are unique and none collide with the `collect` services; the codey bridge publishes `127.0.0.1:9092`; `prometheus-codey.yml` declares jobs for `pushgateway-codey`, `node-exporter-codey`, `cadvisor-codey`, `prometheus-codey`.

**Step 2** Run the test — expect FAIL (services missing).

**Step 3** Add the services and config file; add `prometheus-codey.yml` to the world-readable list.

**Step 4** `python -c 'import yaml...'` parse both files, `docker compose -f monitor/docker-compose.yml --profile ui config --quiet` locally if docker is available, re-run tests PASS.

**Step 5** Commit: `feat(monitor): add local collector stack for codey's ui profile`

### Task 3: Grafana datasource + codey alert rules

**Files:**
- Modify: `monitor/provisioning/datasources/datasources.yml`
- Create: `monitor/provisioning/alerting/alert-rules-codey.yml`
- Test: `ansible/tests/monitor_codey/test_alert_rules.py`

**Step 1** Test: rendered datasource template contains uid `prometheus-codey` with `url: http://prometheus-codey:9090`; every rule in `alert-rules-codey.yml` uses `datasourceUid: prometheus-codey`, has a unique uid, a severity label and `noDataState`; the main `alert-rules.yml` is untouched.

**Step 2** Run test — expect FAIL.

**Step 3** Add datasource and rules (host CPU/mem/load/PSI/disk, container OOM/near-limit/down/unhealthy/probe-stale).

**Step 4** Validate YAML, re-run tests PASS.

**Step 5** Commit: `feat(monitor): add codey datasource and focused alert rules`

### Task 4: Render Loki password on ui hosts

**Files:**
- Modify: `ansible/plays/user.yml` (render task `when`)
- Test: extend `ansible/tests/monitor_codey/test_render.py` (or Molecule `docker_service/default` verify) asserting the task condition includes `ui`.

**Steps:** RED → change `when` to `('collect' in profiles) or ('ui' in profiles)` → GREEN → commit `fix(monitor): render Loki push password on ui hosts too`.

### Task 5: monitor_reload third half

**Files:**
- Create: `ansible/plays/roles/monitor_reload/tasks/prometheus-codey.yml`
- Modify: `ansible/plays/roles/monitor_reload/defaults/main.yml`
- Modify: `ansible/plays/roles/monitor_reload/tasks/main.yml`
- Modify: `ansible/plays/user.yml` (vars)
- Modify: `ansible/plays/roles/monitor_reload/molecule/default/converge.yml`
- Modify: `ansible/plays/roles/monitor_reload/molecule/default/verify.yml`

**Step 1** Extend the Molecule scenario: fixture `prometheus-codey.yml`; a third include_role run with only the new half enabled; verify a third state file exists and its fingerprint covers the new file and differs from the other two.

**Step 2** Run `molecule test` in the role — expect FAIL (no third half).

**Step 3** Implement the task file, defaults, main.yml import and user.yml var; extend verify.

**Step 4** Molecule PASS.

**Step 5** Commit: `feat(monitor_reload): fingerprint and restart codey's Prometheus`

### Task 6: Container-health probe on codey

**Files:**
- Modify: `ansible/plays/roles/system_probe/defaults/main.yml`
- Modify: `ansible/plays/roles/system_probe/tasks/main.yml`
- Modify: `ansible/plays/roles/system_probe/molecule/no-sink/converge.yml`
- Modify: `ansible/plays/roles/system_probe/molecule/no-sink/verify.yml`

**Step 1** Extend `no-sink` scenario: with `ui` profile and global push disabled, the container-health script/timer must exist while the other probes are removed; push URL must point at 9092. Expect FAIL.

**Step 2** Add `system_probe_container_push_enabled` (true when `ui` active), gate the two container probe tasks on it, exempt `system-container-health` from the no-sink cleanup, and make `system_probe_pushgateway_url` profile-aware (9092 with `ui`, else 9091).

**Step 3** Molecule PASS (both `default` and `no-sink`).

**Step 4** Commit: `feat(system_probe): run container-health probe on codey's local sink`

### Task 7: Docs, map, history, validation

**Files:**
- Modify: `architecture/landscape.yaml`
- Modify: `monitor/AGENTS.md`
- Modify: `.claude/skills/check-server-status/SKILL.md` (stale "monitor only on servy" bullet)
- Create: `history/2026-11-25_monitor-codey-coverage.md` (ADR, Accepted after deploy)
- Delete: both `docs/plans/2026-11-25_monitor-codey-coverage*` files

**Steps:** run `architecture/render.py --verify --verify-host servy.lehel.xyz --verify-host codey.lehel.xyz`, `ansible-playbook servyy.yml --syntax-check -i testing` and `-i production`, `yamllint`, `git-crypt status`, all unit tests; update map/AGENTS/history; delete plans; commit.

### Task 8: Test deployment then production (gated)

**Steps:** deploy to `servyy-test.lxd` with `./servyy-test.sh`, verify containers/datasources/rules/probe, fix any findings, then **ask user for explicit production approval** naming codey + servy, deploy with `--tags user.docker.monitor,system.probe --limit ...`, verify, update history ADR to Accepted with real results.
