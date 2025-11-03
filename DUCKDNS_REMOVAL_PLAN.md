# DuckDNS Removal Plan

**Created:** 2025-11-03
**Status:** Planning
**Reason:** Domain `lehel.xyz` now owned via Porkbun, DuckDNS no longer needed

---

## Overview

Since the domain `lehel.xyz` is now purchased through Porkbun, the DuckDNS dynamic DNS service is no longer necessary. This plan outlines the steps to safely remove all DuckDNS-related code and configuration.

---

## Phase 1: Audit Current DuckDNS Usage

### Files to Review

```bash
# Code files
duckdns/update_duckdns.sh                                    # DuckDNS update script
ansible/plays/roles/user/tasks/dyndns.yml                    # Ansible task for DuckDNS
ansible/production                                           # Inventory with duckdns config

# Check for references
grep -r "duckdns\|duck_" ansible/
grep -r "duckdns\|duck_" scripts/
```

### Current Components

1. **Directory:** `duckdns/`
   - `update_duckdns.sh` - Script to update DuckDNS API
   - `.gitkeep` - Empty placeholder

2. **Ansible Configuration:**
   - `ansible/plays/roles/user/tasks/dyndns.yml` - Creates systemd timer
   - `ansible/production` - Contains `duckdns.host: servyy` config

3. **Systemd Service (on deployed servers):**
   - `~/.config/systemd/user/duckdns.service`
   - `~/.config/systemd/user/duckdns.timer`

4. **Secrets (encrypted):**
   - `ansible/plays/vars/secrets.yml` - May contain `duck_token`

---

## Phase 2: Verify No Active Dependencies

### Pre-Removal Checks

```bash
# 1. Check if DuckDNS service is running on production
ssh lehel.xyz "systemctl --user status duckdns.timer"
ssh lehel.xyz "systemctl --user status duckdns.service"

# 2. Check DNS is resolving via Porkbun
dig lehel.xyz
dig photoprism.lehel.xyz
dig git.lehel.xyz

# 3. Verify Porkbun DNS configuration
# Manual check in Porkbun console:
# - A record: lehel.xyz → Server IP
# - Wildcard: *.lehel.xyz → Server IP

# 4. Test service accessibility
curl -I https://photoprism.lehel.xyz
curl -I https://git.lehel.xyz
curl -I https://social.lehel.xyz
```

### Expected Results

- ✅ DNS resolves correctly via Porkbun
- ✅ All services accessible via {service}.lehel.xyz
- ✅ SSL certificates working (Let's Encrypt via Traefik)
- ⚠️ DuckDNS timer may still be running (will be disabled)

---

## Phase 3: Disable DuckDNS on Production Servers

### Stop and Disable Services

```bash
# On lehel.xyz
ssh lehel.xyz << 'EOF'
  # Stop and disable timer
  systemctl --user stop duckdns.timer
  systemctl --user disable duckdns.timer

  # Stop service (if running)
  systemctl --user stop duckdns.service
  systemctl --user disable duckdns.service

  # Verify stopped
  systemctl --user list-timers | grep duckdns
  systemctl --user list-units | grep duckdns
EOF

# On aqui.fritz.box (if applicable)
ssh aqui.fritz.box << 'EOF'
  systemctl --user stop duckdns.timer 2>/dev/null || true
  systemctl --user disable duckdns.timer 2>/dev/null || true
  systemctl --user stop duckdns.service 2>/dev/null || true
  systemctl --user disable duckdns.service 2>/dev/null || true
EOF
```

### Remove Systemd Files (Optional - will be removed on next deployment)

```bash
ssh lehel.xyz "rm -f ~/.config/systemd/user/duckdns.service"
ssh lehel.xyz "rm -f ~/.config/systemd/user/duckdns.timer"
ssh lehel.xyz "systemctl --user daemon-reload"
```

---

## Phase 4: Remove from Ansible Configuration

### Step 1: Remove Ansible Task File

```bash
# Backup first
cp ansible/plays/roles/user/tasks/dyndns.yml ansible/plays/roles/user/tasks/dyndns.yml.backup

# Option A: Delete the file
rm ansible/plays/roles/user/tasks/dyndns.yml

# Option B: Keep file but comment everything out (safer)
# (Manual edit to comment out all tasks)
```

### Step 2: Remove Import from Main Playbook

**File:** `ansible/plays/roles/user/tasks/main.yml`

Find and remove/comment:
```yaml
# Remove these lines:
- import_tasks: dyndns.yml
  tags:
    - user.dyndns
  when: duckdns is defined
```

### Step 3: Remove from Inventory

**File:** `ansible/production`

```yaml
# Before:
lehel.xyz:
  with_docker: true
  with_containers: true
  has_10g_volume: true
  create_swap: true
  duckdns:              # ← Remove this section
    host: servyy        # ← Remove this line

# After:
lehel.xyz:
  with_docker: true
  with_containers: true
  has_10g_volume: true
  create_swap: true
```

### Step 4: Remove Secrets (if present)

**File:** `ansible/plays/vars/secrets.yml` (encrypted)

```bash
# Unlock secrets file
cd ansible/plays/vars
git-crypt unlock

# Edit secrets.yml and remove:
# duck_token: "xxxxx"

# Re-lock
git add secrets.yml
git commit -m "chore: remove deprecated DuckDNS token"
```

---

## Phase 5: Remove DuckDNS Directory

### Option A: Complete Removal

```bash
# Remove directory
rm -rf duckdns/

# Commit change
git add duckdns/
git commit -m "chore: remove deprecated DuckDNS service

DuckDNS is no longer needed since domain lehel.xyz
is now owned via Porkbun with static DNS configuration."
```

### Option B: Keep as Archive (Recommended Initially)

```bash
# Rename to indicate deprecated status
mv duckdns/ _deprecated_duckdns/

# Update .gitignore if needed
echo "_deprecated_*" >> .gitignore

# Commit
git add duckdns/ _deprecated_duckdns/ .gitignore
git commit -m "chore: deprecate DuckDNS service (now using Porkbun)"
```

---

## Phase 6: Update Documentation

### Files Already Updated

- ✅ `Claude.md` - Updated to reference Porkbun DNS
- ✅ Service naming section - Removed DuckDNS references
- ✅ Architecture diagrams - Show Porkbun instead

### Additional Documentation

Create/Update:
- ✅ `DUCKDNS_REMOVAL_PLAN.md` (this file)
- Consider: `PORKBUN_DNS_SETUP.md` with DNS configuration

---

## Phase 7: Test Deployment

### Deploy to Test Container

```bash
# Create test container
cd scripts
./setup_test_container.sh

# Deploy with DuckDNS removed
cd ../ansible
ansible-playbook testing.yml

# Verify no errors related to duckdns tasks
# Check that all services start correctly
```

### Deploy to Production

```bash
cd ansible
./servyy.sh

# Expected behavior:
# - No duckdns.timer created
# - All other services work normally
# - DNS resolution via Porkbun works
```

### Verification

```bash
# 1. Check no DuckDNS systemd units
ssh lehel.xyz "systemctl --user list-units | grep duckdns"
# Expected: No output

# 2. Verify services accessible
for service in photoprism git social monitor; do
  echo "Testing ${service}.lehel.xyz..."
  curl -I https://${service}.lehel.xyz
done

# 3. Check Traefik routing
ssh lehel.xyz "docker logs traefik 2>&1 | grep -i error"
```

---

## Phase 8: Cleanup Legacy Files on Servers

### Remove Old DuckDNS Files

```bash
# On production servers
ssh lehel.xyz << 'EOF'
  # Remove directory (if it was deployed)
  rm -rf ~/containers/duckdns/

  # Remove systemd files (if not already removed)
  rm -f ~/.config/systemd/user/duckdns.service
  rm -f ~/.config/systemd/user/duckdns.timer

  # Reload systemd
  systemctl --user daemon-reload
EOF
```

---

## Rollback Plan

If issues arise after removal:

### Quick Rollback

```bash
# 1. Restore from backup
git checkout HEAD~1 -- duckdns/
git checkout HEAD~1 -- ansible/plays/roles/user/tasks/dyndns.yml
git checkout HEAD~1 -- ansible/production

# 2. Redeploy
cd ansible
./servyy.sh

# 3. Verify DuckDNS timer running
ssh lehel.xyz "systemctl --user status duckdns.timer"
```

### Manual Activation

```bash
# If Porkbun DNS fails, temporarily use DuckDNS
ssh lehel.xyz << 'EOF'
  cd ~/containers/duckdns
  ./update_duckdns.sh servyy YOUR_TOKEN
EOF
```

---

## Migration Checklist

### Pre-Removal

- [ ] Verify Porkbun DNS configured
  - [ ] A record: `lehel.xyz` → Server IP
  - [ ] Wildcard: `*.lehel.xyz` → Server IP
  - [ ] AAAA record (if IPv6): `lehel.xyz` → IPv6
- [ ] Test DNS resolution: `dig lehel.xyz`
- [ ] Test service access: `curl https://photoprism.lehel.xyz`
- [ ] Backup current configuration

### Removal Process

- [ ] Stop DuckDNS timer on production
- [ ] Disable DuckDNS service on production
- [ ] Remove `dyndns.yml` from Ansible
- [ ] Remove import from `main.yml`
- [ ] Remove `duckdns` section from inventory
- [ ] Remove `duck_token` from secrets (optional)
- [ ] Remove/deprecate `duckdns/` directory
- [ ] Update documentation (✅ Already done)

### Testing

- [ ] Deploy to test container successfully
- [ ] Deploy to production successfully
- [ ] Verify no DuckDNS systemd units
- [ ] Verify all services accessible
- [ ] Check SSL certificates renewing
- [ ] Monitor for 24-48 hours

### Post-Removal Cleanup

- [ ] Remove systemd files from servers
- [ ] Remove `~/containers/duckdns/` from servers
- [ ] Clean up backup files
- [ ] Update any external documentation
- [ ] Consider removing DuckDNS account (optional)

---

## Timeline

**Recommended approach:** Phased removal over 1-2 weeks

1. **Week 1:**
   - Disable DuckDNS timer (keep code)
   - Monitor DNS resolution via Porkbun
   - Verify stability

2. **Week 2:**
   - If stable, proceed with code removal
   - Deploy changes
   - Final cleanup

**Aggressive approach:** Same day (if confident in Porkbun setup)

---

## Notes

### Why Keep duckdns/ Directory Initially?

- Provides easy rollback option
- Historical reference for similar setups
- No harm in keeping deprecated code temporarily

### Future Considerations

If server IP changes frequently, consider:
- Porkbun dynamic DNS API (similar to DuckDNS)
- Cloudflare DNS with API updates
- Keep static IP via Hetzner Cloud

### Porkbun DNS Configuration

**Recommended DNS records:**
```
Type    Host        Value               TTL
A       @           <server-ipv4>       600
A       *           <server-ipv4>       600
AAAA    @           <server-ipv6>       600 (optional)
AAAA    *           <server-ipv6>       600 (optional)
```

This ensures:
- `lehel.xyz` → Server
- `*.lehel.xyz` → Server (all subdomains)
- Fast updates (10 min TTL)

---

## Contacts & Resources

- **Porkbun Console:** https://porkbun.com/account/domainsSpeech
- **DNS Propagation Check:** https://www.whatsmydns.net/
- **SSL Certificate Check:** https://www.ssllabs.com/ssltest/

---

**Status:** Ready for execution
**Risk Level:** Low (DNS already working via Porkbun)
**Estimated Time:** 2-4 hours (including testing)
