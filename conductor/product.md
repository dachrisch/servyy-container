# Initial Concept
servyy-container is a self-hosted infrastructure platform managing over 15 microservices using Ansible for orchestration and Docker Compose for service definitions.

# Product Definition

## Vision
To provide a robust, automated, and secure self-hosted environment for personal microservices, following GitOps principles where the infrastructure state is entirely defined in code.

## Primary Goals
- **Security & Hardening:** Enhance the security of the host system and the services it runs using tools like fail2ban, Monit, and firewalls.
- **Reliability & Monitoring:** Maintain high uptime and visibility into service health through a comprehensive observability stack (Prometheus, Grafana, Loki).
- **Service Expansion:** Provide a scalable framework for migrating and hosting additional microservices with minimal manual intervention.

## Target Audience
Self-hosters and developers looking for a professional-grade, automated approach to managing their private server infrastructure.

## Key Features
- **Automated Deployment:** Ansible-driven orchestration for system configuration and Docker Compose management.
- **Centralized Logging:** Log aggregation using Loki and Promtail for all containers and system services.
- **Secure Secret Management:** Protection of sensitive data using git-crypt.
- **Automated Backups:** Daily offsite backups of critical data using Restic to Hetzner Storagebox.
- **Infrastructure as Code:** Every change is documented in history and applied via Git-triggered playbooks.