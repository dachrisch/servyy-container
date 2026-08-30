# Security Audit - servy.lehel.xyz (2026-08-30)

## Problem
Perform comprehensive security audit of servy.lehel.xyz to identify attack surface and vulnerabilities, especially important since we handle customer data.

## Solution
Deployed automated security audit system using 7 open-source tools:
- **Lynis** - Host OS hardening (CIS-like)
- **Docker Bench Security** - Docker CIS Benchmark v1.6.0
- **Trivy** - Container image CVE scanner
- **Nmap** - Network port scan
- **testssl.sh** - TLS/SSL configuration
- **humble** - HTTP security headers (62+ checks)
- **Nuclei** - Web vulnerability scanner

## Files Changed
- `ansible/plays/vars/default.yml` - Security audit variables
- `ansible/plays/roles/system/tasks/main.yml` - Import security_audit.yml
- `ansible/plays/roles/system/tasks/security_audit.yml` - Install + deploy tasks
- `ansible/plays/roles/system/templates/security-audit.sh.j2` - Orchestrator script
- `ansible/plays/roles/system/templates/security-audit.service.j2` - systemd service
- `ansible/plays/roles/system/templates/security-audit.timer.j2` - systemd timer
- `ansible/plays/roles/system/templates/logrotate-security-audit.j2` - Log rotation

## Audit Results (2026-08-30)

### Lynis - Host OS (Score: 58/100)

**3 Warnings:**
- `KRNL-5830` - Reboot needed after kernel update
- `PKGS-7392` - Vulnerable packages found
- `DBS-1820` - MongoDB allows any user to access databases (CRITICAL!)

**Key Suggestions:**
- Set GRUB bootloader password (`BOOT-5122`)
- Configure password hashing rounds (`AUTH-9230`)
- Install PAM password strength module (`AUTH-9262`)
- Set min/max password age (`AUTH-9286`)
- Improve default umask to 027 (`AUTH-9328`)
- Separate /home and /var partitions (`FILE-6310`)
- Install debsums for package verification (`PKGS-7370`)
- Purge 13 old/removed packages (`PKGS-7346`)

### Docker Bench (FAILED - needs fix)
- Container couldn't connect to Docker daemon
- Fix: Added `--privileged` flag to container run command

### Trivy - Container Vulnerabilities
- **58 CRITICAL CVEs** across container images
- **1,707 HIGH CVEs** across container images
- Multiple images affected including base images

### Nmap - Network
**6 open ports on localhost:**
| Port | Service | Status |
|------|---------|--------|
| 22 | SSH | Expected |
| 80 | HTTP (Traefik) | Expected |
| 443 | HTTPS (Traefik) | Expected |
| 8082 | Traefik metrics | Expected |
| 9091 | Pushgateway | Expected |
| 32768 | nginx | Unexpected - investigate |

### Security Headers (humble - Grade D)
**All 5 scanned endpoints scored D:**

| Endpoint | Enabled | Missing | Deprecated | Grade |
|----------|---------|---------|------------|-------|
| servy.lehel.xyz | 1 | 15 | 1 | D |
| traefik.lehel.xyz | 2 | 14 | 1 | D |
| git.lehel.xyz | 1 | 14 | 2 | D |
| grafana.lehel.xyz | 2 | 13 | 1 | D |
| portainer.lehel.xyz | 5 | 9 | 13 | D |

**Critical Missing Headers (all endpoints):**
- `Strict-Transport-Security` (HSTS)
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Content-Security-Policy`
- `Referrer-Policy`
- `Permissions-Policy`
- `Cross-Origin-*` policies

### TLS/SSL (testssl.sh)
- FAILED: Missing `openssl` binary
- Fix: Added `openssl` to packages list

### Web Vulnerabilities (nuclei)
- FAILED: Wrong flag format (`-json` → `-je`)
- Fix: Updated script to use `-je` flag

## Fixes Applied
1. Docker Bench: Added `--privileged` flag for proper Docker socket access
2. testssl.sh: Added `openssl` to Ansible packages list
3. nuclei: Changed `-json` to `-je` flag for newer version compatibility
4. Trivy JSON: Fixed malformed JSON output format

## Immediate Actions Recommended

1. **CRITICAL**: Fix MongoDB authentication (`DBS-1820`) - currently allows any user access
2. **HIGH**: Add security headers via Traefik middleware (HSTS, CSP, X-Frame-Options)
3. **HIGH**: Update container base images to fix CRITICAL CVEs
4. **MEDIUM**: Set GRUB password, password policies
5. **MEDIUM**: Investigate port 32768 (nginx) - unexpected open port
6. **LOW**: Purge 13 old/removed packages

## Deployment
```bash
# Deploy audit system
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags system.security_audit

# Run audit manually
ssh servy.lehel.xyz 'sudo systemctl start security-audit.service'

# Check results
ssh servy.lehel.xyz 'ls -la /var/log/security-audit/$(date +%Y-%m-%d)/'

# View Lynis score
ssh servy.lehel.xyz 'grep "hardening_index" /var/log/security-audit/$(date +%Y-%m-%d)/lynis-report.dat'

# Count vulnerabilities
ssh servy.lehel.xyz 'grep -c "Severity": "CRITICAL" /var/log/security-audit/$(date +%Y-%m-%d)/trivy-results.json'
```

## Automation
- **systemd timer**: Monthly on 1st Sunday at 04:00 UTC
- **Log rotation**: 6-month retention
- **Results**: `/var/log/security-audit/YYYY-MM-DD/`
