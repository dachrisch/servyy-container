---
name: opencode-ssh-validation
description: Validate OpenCode SSH key configuration, GitHub authentication, and container health
---

# OpenCode SSH Validation Skill

Validates OpenCode's SSH key setup, GitHub authentication, and operational health.

## When to Use

- After deploying a new SSH key to OpenCode
- Troubleshooting OpenCode git/GitHub connectivity issues
- Pre-deployment verification before production changes
- Post-restart health check after container updates

## What It Checks

1. **SSH Key File**
   - Exists at `/root/.ssh/id_github`
   - Correct permissions (0600)
   - Correct ownership (root:root)

2. **SSH Configuration**
   - GIT_SSH_COMMAND environment variable is set
   - SSH config includes GitHub host entries (if needed)
   - known_hosts has GitHub key

3. **GitHub Authentication**
   - SSH connection to git@github.com succeeds
   - Public key authentication working
   - Permission errors are resolved

4. **Git Operations**
   - git clone from GitHub repositories
   - git pull on existing repositories
   - git push operations

5. **Container Health**
   - Container is running
   - Application listening on port 4096
   - Health check endpoint responding

6. **Provisioning Status**
   - Dev checkout repositories are updated
   - No unrecoverable provision errors

## Typical Output

```
=== SSH Key ===
✅ File exists: /root/.ssh/id_github (411 bytes)
✅ Permissions: -rw------- (0600)
✅ Ownership: root:root

=== GitHub Authentication ===
✅ SSH connection successful
✅ Public key authentication: PASSED
✅ GitHub fingerprint verified

=== Git Operations ===
✅ git clone: PASSED
✅ Existing repo status: ON BRANCH master
✅ git pull: NO UPDATES

=== Container Health ===
✅ Container running: opencode.web
✅ Health check: RESPONDING
✅ Provisioning: COMPLETED
```

## Troubleshooting Guide

| Issue | Cause | Fix |
|-------|-------|-----|
| `Identity file not accessible` | Wrong file permissions | `docker exec opencode.web chown root:root /root/.ssh/id_github && chmod 600 /root/.ssh/id_github` |
| `Permission denied (publickey)` | SSH key not in GitHub | Add public key to https://github.com/settings/keys |
| `git clone failed` | SSH key auth issue OR key not accessible | Check permissions + GitHub key configuration |
| `Container not responding` | App crashed or not started | Check `docker logs opencode.web` for errors |
| `Provision warnings` | Normal if repos already cloned | Only block if git auth explicitly fails |

## Implementation

When invoked, this skill will:

1. **SSH Check** - Verify key file exists with correct permissions and ownership
2. **Environment Check** - Confirm GIT_SSH_COMMAND is properly configured
3. **Auth Test** - Run SSH connection test to GitHub
4. **Git Test** - Attempt git clone or status check
5. **Health Check** - Verify container and application are responsive
6. **Report** - Generate validation report with status and any issues

If any check fails, the report will include:
- What failed
- Why it likely failed
- Remediation steps

## Quick Command Reference

```bash
# Full validation
docker exec opencode.web sh -c '
  echo "=== SSH Key ===" &&
  ls -l /root/.ssh/id_github &&
  echo "" &&
  echo "=== GIT_SSH_COMMAND ===" &&
  env | grep GIT_SSH &&
  echo "" &&
  echo "=== GitHub Auth Test ===" &&
  ssh git@github.com 2>&1 | grep -i "authenticated\|permission" &&
  echo "" &&
  echo "=== Git Clone Test ===" &&
  cd /tmp && timeout 10 git clone git@github.com:dachrisch/servyy-container.git test-opencode-validate 2>&1 | head -5
'
```

## See Also

- SSH key incident recovery: `history/2026-08-25_ssh-key-incident-recovery.md`
- OpenCode docker-compose: `opencode/docker-compose.yml`
- GitHub SSH keys settings: https://github.com/settings/keys
