# Technology Stack

## Core Infrastructure
- **Orchestration:** Ansible (Modular roles and playbooks for system and service management)
- **Containerization:** Docker & Docker Compose v2 (Service isolation and definition)
- **Reverse Proxy:** Traefik (Edge router with Let's Encrypt DNS-01 challenge automation)

## Observability & Monitoring
- **Metrics:** Prometheus (Time-series data collection)
- **Log Aggregation:** Loki & Promtail (Centralized log management for containers and system)
- **Visualization:** Grafana (Dashboards for metrics, logs, and alerting status)
- **Host Monitoring:** Monit (Process and system resource monitoring with local alerting)

## Security & Data Protection
- **Intrusion Prevention:** fail2ban (Integrated with Loki for log-based banning)
- **Secret Management:** git-crypt (Transparent file encryption within the Git repository)
- **Backups & Recovery (Primary):** Restic (Encrypted backups and automated restoration via restic_restore.yml)
- **Backups (Legacy/Secondary):** rsync (Used for specific data transfers and legacy backup paths)
- **Firewall:** Hetzner Cloud Firewall & local iptables/nftables management via Ansible

## Automation & Scripting
- **Languages:** Python (Ansible modules, automation scripts), Bash (Utility scripts)
- **Configuration:** YAML (Ansible, Docker Compose, Traefik dynamic configs)