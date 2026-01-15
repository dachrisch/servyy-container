# Product Guidelines

## Core Principles

### GitOps First
All changes to the infrastructure and services MUST be defined in this repository and applied via Ansible. Manual modifications to the server state are strictly forbidden to ensure the repository remains the single source of truth.

### Automate Everything
Manual intervention should be minimized. Repetitive maintenance tasks, such as backups, security updates, log rotation, and system cleanup, must be implemented as automated Ansible tasks or systemd timers.

### Observability as a Requirement
A service is not considered fully deployed or operational until it is integrated into the observability stack. This includes:
- Standardized logging to Loki via Promtail.
- Basic metric collection by Prometheus.
- Inclusion in health monitoring and alerting via Monit or Grafana alerts.

## Deployment Standards
- **Testing:** Major changes should be verified in the `servyy-test.lxd` environment before production rollout.
- **Traceability:** Every deployment must be linked to a Git commit, and significant infrastructure changes must be documented in the `history/` directory.
- **Security:** Secrets must never be stored in plain text and should be managed via `git-crypt`.