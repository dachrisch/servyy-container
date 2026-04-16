# 2026-04-16 Monit Configuration and Watchtower Consolidation Fix

## Context
Following the consolidation of Watchtower instances into the `portainer` service and the termination of the `monitor` (Grafana) service, the Monit configuration on `lehel.xyz` was reporting multiple stale failures. Additionally, the `10g_volume` mount had been removed but was still being monitored.

## Changes
- **Ansible Inventory:** Set `has_10g_volume: false` for `lehel.xyz` to remove the stale filesystem check.
- **Service Monitoring:** Marked the `monitor` service as `manual: {}` in `ansible/plays/vars/secrets.yml` to stop Monit from checking the retired Grafana container.
- **Monit Scripts:** Regenerated the Monit check scripts via Ansible. This updated the container name targets (e.g., `opencode.api` and `leagues-finance.finance-api`) and correctly incorporated the consolidated watchtowers (`portainer.watchtower-prod` and `portainer.watchtower-dev`) under the Portainer service check.

## Verification
- Ran `./servyy.sh --tags system.monit --limit lehel.xyz`.
- Verified `monit status` on the production server. All services are reporting `OK` or are successfully initializing.
- Manually ran `/etc/monit/scripts/check_docker_compose-portainer.sh` to confirm it correctly detects all three containers in the portainer stack.
