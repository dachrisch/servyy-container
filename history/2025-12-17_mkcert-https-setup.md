# Automated mkcert HTTPS Setup for Test Environment

**Date:** 2025-12-17
**Status:** Deployed & Verified

## Problem

Test environment needed trusted HTTPS certificates but Let's Encrypt wasn't suitable:
- Private infrastructure (not publicly accessible)
- HTTP-01 challenge requires public web access
- DNS-01 would expose internal test infrastructure
- Application requires HTTPS for full functionality

## Solution

Implemented automated mkcert-based HTTPS using local Certificate Authority:
- Fully automated Ansible deployment
- 10-year certificate validity
- No browser warnings after CA installation
- Complete test/production isolation

## Implementation

**Files Created:**
- Ansible task: `roles/testing/tasks/mkcert.yml`
- Handler: `roles/testing/handlers/main.yml`
- Template: `roles/testing/templates/mkcert/README-mkcert.md.j2`

**Files Modified:**
- `roles/testing/tasks/main.yml` - Added import
- `vars/default.yml` - Added mkcert config
- Traefik config files (via blockinfile)

**Deployment:**
```bash
ansible-playbook servyy.yml -i testing --limit <host> --tags testing.mkcert
```

## Verification

- ✅ HTTPS working without warnings
- ✅ Certificates valid for 10 years
- ✅ CA installed locally
- ✅ Production environment unaffected

## Git Commits

- `4c96534` - feat(ansible): add automated mkcert HTTPS setup
- `38079de` - chore(vaultwarden): update admin token

## Success Criteria

All functional, technical, and operational requirements met:
- Zero manual steps
- Idempotent deployment
- Proper file permissions
- Complete documentation
