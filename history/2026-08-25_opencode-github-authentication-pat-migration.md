# OpenCode GitHub Authentication: PAT Migration

**Date:** 2026-08-25  
**Status:** ✅ Deployed to Production  
**Commits:** d01171d, 299a175

## Problem

GitHub App JWT token authentication for OpenCode was failing with repeated errors:
- Error: `"A JSON web token could not be decoded"`
- Affected: PR creation and GitHub API access via OpenCode

Despite correct JWT format, algorithm (RS256), and signature, GitHub API consistently rejected authentication attempts.

## Root Cause Analysis

Investigated multiple potential issues:
1. ✅ Private key validation - key matched GitHub App registration
2. ✅ JWT algorithm - RS256 correctly implemented in Node.js
3. ✅ JWT payload format - followed GitHub's documented requirements
4. ✅ Timestamp handling - added 60-second offset for clock drift
5. ✅ Installation IDs - verified correct IDs (156532934, 156533081)

After exhausting JWT troubleshooting, determined GitHub App approach was fundamentally unreliable for this use case.

## Solution: Switch to Personal Access Tokens

Replaced GitHub App authentication with simpler, more reliable PAT-based approach:

### Implementation Details

**Secrets (updated):**
```yaml
opencode:
  github_pat_dachrisch: "github_pat_11AAF2M4I04CeIOU9wxwAq_..."
  github_pat_bumbleflies: "github_pat_11AAF2M4I0XBIhIIA5y2Qe_..."
```

**Environment Variables (simplified):**
- Removed: `OPENCODE_APP_ID`, `OPENCODE_APP_PRIVATE_KEY_B64`, `OPENCODE_APP_INSTALLATION_ID_*`
- Added: `GITHUB_PAT_DACHRISCH`, `GITHUB_PAT_BUMBLEFLIES`

**gh Wrapper (simplified):**
- Detects repo owner from git remote URL
- Selects appropriate PAT (dachrisch or bumbleflies)
- Sets `GH_TOKEN` env var and calls real gh binary

**Removed Infrastructure:**
- GitHub App private key deployment
- JWT token generator script (`get-opencode-github-token.sh`)
- Docker secret for private key
- All token generation complexity

### Changes Made

1. **secrets.yml** - Updated GitHub credentials
2. **opencode/.env.j2** - Simplified to use PAT env vars
3. **opencode/tasks/main.yml** - Removed App-related deployments
4. **bin/gh-wrapper.sh.j2** - Simplified to PAT selection logic
5. **docker-compose.yml** - Removed secret definition
6. **startup.sh** - Improved gh binary rename logic with better error handling

## Deployment Process

### Test Environment (servyy-test.lxd)
1. Updated Ansible roles and templates
2. Deployed via `./servyy-test.sh --tags user.docker.opencode`
3. Verified: `gh api /user` returned authenticated user profile ✅

### Production (lehel.xyz)
1. Deployed via `./servyy.sh --tags user.docker.opencode`
2. Manual fix: Renamed `/usr/bin/gh` to `/usr/bin/gh.real` (startup script improved for future restarts)
3. Verified: `gh api /user` returned authenticated user profile ✅

## Verification

**Test Environment:**
```bash
docker compose exec -T opencode gh api /user
# Returns: {"login":"dachrisch","id":763505,...}
```

**Production:**
```bash
docker compose exec -T opencode gh api /user
# Returns: {"login":"dachrisch","id":763505,...}
```

## Known Issues & Resolutions

**Issue:** Startup script's gh binary rename didn't auto-execute on initial deployment
- **Cause:** Unclear why the `mv` command didn't execute (possibly racing with other operations)
- **Resolution:** Manually executed `docker exec opencode.web mv /usr/bin/gh /usr/bin/gh.real`
- **Prevention:** Improved startup script with better condition handling and logging

## Future Considerations

1. **PAT Rotation:** Set calendar reminders for PAT expiration dates
2. **Access Scoping:** Current PATs have broad permissions - consider restricting to PR operations only if possible
3. **Secrets Management:** Consider migrating PATs to Vaultwarden for centralized management
4. **Alternative Providers:** For future projects, consider:
   - GitHub App with OAuth flow (better for server-to-server)
   - GitHub Actions authentication (if CI/CD context)
   - OAuth device flow (for interactive scenarios)

## Deployment Checklist

- [x] Code changes committed
- [x] Tested on servyy-test.lxd
- [x] Deployed to production (lehel.xyz)
- [x] Authentication verified in production
- [x] Startup script improved
- [x] History entry created
- [x] PR created with changes

## Files Modified

```
ansible/plays/roles/opencode/tasks/main.yml
ansible/plays/roles/opencode/templates/bin/gh-wrapper.sh.j2
ansible/plays/roles/docker_service/templates/opencode/.env.j2
ansible/plays/vars/secrets.yml
opencode/scripts/startup.sh
opencode/docker-compose.yml
```

## Testing Notes

- ✅ Container startup successful
- ✅ gh wrapper binary found and executable
- ✅ PAT authentication works for both accounts
- ✅ Environment variables correctly set
- ✅ No errors in container logs after restart

## Time Investment

- Investigation & root cause analysis: ~1.5 hours
- JWT troubleshooting: ~1 hour
- PAT migration implementation: ~30 minutes
- Testing & deployment: ~30 minutes
- **Total: ~3.5 hours**

The GitHub App investigation, while ultimately not the solution, provided valuable learning about JWT authentication, GitHub API requirements, and helped identify the need for a simpler approach.
