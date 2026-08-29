# DNS Infrastructure Restructuring - 2026-08-29

## Summary

Restructured lehel.xyz DNS architecture to clarify infrastructure topology and enable programmatic DNS management via Porkbun API. Created `dns-master` agent for ongoing DNS infrastructure automation.

**Status**: ✅ Complete (Phase 1-3)

---

## Problem Statement

### Before
- DNS structure conflated server names with domain routing
- No infrastructure-as-code tool for DNS management
- Manual DNS changes via Porkbun dashboard
- Asymmetric naming: most services used `service.lehel.xyz`, but opencode was `code.lehel.xyz` (server name as domain)
- No clear separation between "actual server IPs" and "public-facing service routes"

### Root Cause
DNS grew organically without deliberate architecture. The Traefik reverse proxy abstracted away server topology, but DNS didn't reflect this clearly.

---

## Solution Implemented

### Phase 1: DNS Restructuring (Completed)

#### DNS Layout Changes

**Before:**
```
code.lehel.xyz → A: 217.217.227.124 (server IP exposed)
code.lehel.xyz → AAAA: 2a01:8740:1:fa3::54ad
```

**After:**
```
codey.lehel.xyz → A: 217.217.227.124 (internal server name)
codey.lehel.xyz → AAAA: 2a01:8740:1:fa3::54ad
code.lehel.xyz → CNAME → codey.lehel.xyz (public alias)
```

**Benefits:**
- Clearer infrastructure topology (codey = server, code = public alias)
- Services on codey still accessible via `code.lehel.xyz` (backward compatible)
- Server infrastructure details hidden from users
- Foundation for future multi-server routing

#### Complete DNS Architecture

```
Root Domain:
  lehel.xyz → ALIAS → servy.lehel.xyz (primary server)

Primary Server (servy.lehel.xyz):
  - A: 49.13.6.173
  - AAAA: 2a01:4f8:c013:f6f4::1
  - Hosts: traefik, git, photoprism, monitor, and 15+ other services

Wildcard Routing (lehel services):
  - *.lehel.xyz → CNAME → servy.lehel.xyz
  - Catches all lehel services automatically (fallback pattern)

Secondary Server (codey.lehel.xyz):
  - A: 217.217.227.124
  - AAAA: 2a01:8740:1:fa3::54ad
  - Internal infrastructure detail (not exposed to users)

Public Alias (code.lehel.xyz):
  - CNAME → codey.lehel.xyz
  - Used by services and users (hides codey name)

Other Servers (if added):
  - agenty.lehel.xyz → A/AAAA (explicit server entry)
```

#### DNS Record Changes

| Record | Type | Before | After | Action |
|--------|------|--------|-------|--------|
| codey.lehel.xyz | A | — | 217.217.227.124 | Created |
| codey.lehel.xyz | AAAA | — | 2a01:8740:1:fa3::54ad | Created |
| code.lehel.xyz | A | 217.217.227.124 | — | Deleted |
| code.lehel.xyz | AAAA | 2a01:8740:1:fa3::54ad | — | Deleted |
| code.lehel.xyz | CNAME | — | codey.lehel.xyz | Created |

#### Credentials Stored

Added Porkbun API keys to `ansible/plays/vars/secrets.yml` (git-crypt encrypted):
```yaml
porkbun_api:
  pk: "pk1_..."  # Public API key
  sk: "sk1_..."  # Secret API key
```

**Security:**
- ✅ Encrypted with git-crypt (safe in git)
- ✅ Never exposed in logs
- ✅ Only used by dns-master agent
- ✅ Has minimum required permissions (DNS read/write on lehel.xyz)

---

### Phase 2: DNS Master Agent (Completed)

#### Agent Created: `.claude/agents/dns-master.md`

**Purpose**: Autonomous infrastructure agent for DNS management

**Capabilities:**
- Query Porkbun API for current DNS records
- Create/update/delete DNS records
- Validate DNS changes before applying (no breaking changes)
- Verify DNS propagation after changes
- Ansible inventory integration (future)
- Dry-run support for testing

**Key Features:**
- Header-based API authentication (safe)
- Structured output for parsing
- Impact analysis before changes
- Rollback guidance
- Documentation of all operations

**Usage Pattern:**
```
User: "Change DNS to X"
Agent: Query current state → Validate → Show impact → Get approval → Execute → Verify
```

**Integration Points:**
- Traefik (DNS for ACME challenges)
- Ansible inventory (services per server)
- Porkbun API v3 (Lehel.xyz domain management)
- Docker services (service-to-DNS mapping)

---

### Phase 3: Documentation Updates (Completed)

#### CLAUDE.md Updates
Added comprehensive DNS Management section:
- DNS architecture diagram
- Agent usage examples
- Credential management explanation
- Common patterns (services on lehel, services on codey)
- Troubleshooting guide
- Porkbun API reference

#### AGENTS.md Updates
Added specialized agents section:
- Listed all available agents
- dns-master agent description and usage
- When to use dns-master vs other agents

#### History Log
Created this file documenting:
- Problem statement
- Solution implemented
- Changes made
- Verification results
- Future enhancements

---

## Verification Results

### DNS Propagation
```
✅ codey.lehel.xyz A record: 217.217.227.124
✅ codey.lehel.xyz AAAA record: 2a01:8740:1:fa3::54ad
✅ code.lehel.xyz CNAME: codey.lehel.xyz
✅ DNS resolves correctly via dig
✅ Services remain accessible
```

### Service Availability
```
✅ code.lehel.xyz accessible (via CNAME)
✅ Codey services work as before
✅ Traefik routing unchanged
✅ HTTPS certificates still valid
✅ No service interruption
```

### Infrastructure Impact
```
✅ No breaking changes to running services
✅ Backward compatibility maintained (code.lehel.xyz still works)
✅ SSH access unchanged
✅ Ansible deployment unchanged
✅ Monitoring/logging unchanged
```

---

## Files Changed

| File | Change | Type |
|------|--------|------|
| `ansible/plays/vars/secrets.yml` | Add porkbun_api credentials | Encrypted |
| `.claude/agents/dns-master.md` | Create DNS infrastructure agent | New file |
| `CLAUDE.md` | Add DNS Management section | Documentation |
| `AGENTS.md` | Add specialized agents listing | Documentation |
| `history/2026-08-29_dns-restructuring.md` | Create this history log | New file |

---

## Known Limitations & Future Enhancements

### Current State
- DNS management is Porkbun-specific (lehel.xyz domain)
- Manual invocation of dns-master agent
- No automatic DNS updates on service deployment

### Future Enhancements

1. **Ansible Integration**
   - Define DNS records in Ansible inventory
   - Playbook templates DNS structure from services_enabled
   - Automatic DNS updates on service deployment/removal

2. **Multi-Domain Support**
   - Extend dns-master to manage other domains
   - Domain-agnostic credential storage
   - Porkbun registrar integration

3. **Service Auto-Discovery**
   - Query Docker services
   - Auto-generate DNS entries from Traefik labels
   - Sync Ansible inventory with discovered services

4. **DNS Validation & Monitoring**
   - Continuous DNS health checks
   - Alert on DNS misconfigurations
   - Validate CNAME chains, TTLs
   - Track certificate ACME challenges

5. **Load Balancing**
   - Support for weighted CNAMEs
   - Service failover via DNS
   - Multi-server service routing

---

## Rollback Procedure

If DNS changes need to be reverted:

```bash
# Query dns-master agent
dns-master: "Show DNS history for lehel.xyz"

# Revert specific records
dns-master: "Restore code.lehel.xyz to A record 217.217.227.124"
dns-master: "Delete codey.lehel.xyz records"

# Verify
dig code.lehel.xyz
dig codey.lehel.xyz  # Should fail
```

**Time to revert**: ~5-10 minutes (includes DNS propagation)

---

## Testing & Validation Checklist

### Pre-Deployment
- [x] Porkbun API keys stored securely in secrets.yml
- [x] API keys have DNS permissions verified
- [x] Dry-run test: Query current DNS records successfully

### Deployment
- [x] Create codey.lehel.xyz A/AAAA records
- [x] Delete code.lehel.xyz A/AAAA records
- [x] Create code.lehel.xyz CNAME to codey.lehel.xyz
- [x] Verify all changes via Porkbun API query

### Post-Deployment
- [x] code.lehel.xyz resolves via CNAME
- [x] codey.lehel.xyz resolves to IPs
- [x] DNS propagation verified (dig, multiple nameservers)
- [x] Codey services accessible via code.lehel.xyz
- [x] Traefik routing unchanged
- [x] HTTPS certificates still valid
- [x] No service interruption observed

### Documentation
- [x] CLAUDE.md updated with DNS section
- [x] AGENTS.md updated with dns-master reference
- [x] History log created
- [x] Agent definition complete and comprehensive

---

## Deployment Notes

- **Zero downtime**: DNS changes took effect immediately
- **Backward compatible**: code.lehel.xyz still works (CNAME)
- **No service restarts needed**: Traefik routing handled internally
- **Credentials secured**: Porkbun keys encrypted in git-crypt
- **Agent-ready**: dns-master can be invoked for future DNS changes

---

## References

- **DNS Master Agent**: `.claude/agents/dns-master.md`
- **Porkbun API**: https://porkbun.com/api/json/v3/documentation
- **CLAUDE.md DNS Section**: DNS Management section in root CLAUDE.md
- **Secrets File**: `ansible/plays/vars/secrets.yml` (git-crypt encrypted)

---

## Success Criteria Met

✅ DNS architecture clearly reflects infrastructure topology
✅ Server names distinct from public-facing domains
✅ DNS management automated via dns-master agent
✅ Credentials stored securely
✅ Documentation complete
✅ Zero service interruption
✅ Backward compatibility maintained
✅ Foundation for future DNS automation

---

**Completed by**: Claude (dns-master agent design & documentation)
**Date**: 2026-08-29
**Estimated impact**: Low (internal infrastructure change, no user-facing changes)
**Approved for production**: ✅ Yes
