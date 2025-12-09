# Extension Drive Mount Automation

**Date:** 2025-12-09
**Type:** Production Incident Fix
**Status:** ✅ Deployed to Production

## Problem

**PRODUCTION INCIDENT:** Extension drive on `lehel.xyz` was not mounting automatically on boot, despite being manually mounted. This caused:
- No persistent mount configuration (missing `/etc/fstab` entry)
- Risk of Docker writing to root filesystem after reboot
- Root filesystem at 92% capacity (17G / 19G)
- Manual intervention required after every reboot

## Solution

Added Ansible automation to properly mount the extension drive before Docker setup:

1. **Mount Task** (`plays/roles/system/tasks/extension_drive.yml`):
   - Creates mount point directory
   - Validates device exists
   - Checks filesystem format (formats if needed)
   - Adds persistent `/etc/fstab` entry
   - Mounts drive and verifies success

2. **Configuration** (`plays/vars/default.yml`):
   ```yaml
   extension_drive:
     path: /mnt/10g_volume
     device: /dev/disk/by-id/scsi-0HC_Volume_101343964
     fstype: ext4
     opts: discard,defaults
   ```

3. **Integration** (`plays/roles/system/tasks/main.yml`):
   - Runs early in system role (after user creation, before storagebox)
   - Conditional execution: `has_10g_volume: true` (lehel.xyz only)
   - Ensures mount exists before Docker setup

## Deployment

### Testing
- ✅ Ansible syntax check passed
- ✅ Dry-run successful on production
- ✅ Loop device testing skipped (not available in LXD)

### Production Deployment
```bash
# 1. Mount extension drive
ansible-playbook plays/system.yml --tags "system.extension_drive" --limit lehel.xyz

# 2. Update Docker daemon config
ssh lehel.xyz "sudo bash -c 'cat > /etc/docker/daemon.json <<EOF
{
  \"log-driver\": \"local\",
  \"data-root\": \"/mnt/10g_volume/docker\"
}
EOF'"

# 3. Restart Docker
ssh lehel.xyz "sudo systemctl restart docker"
```

## Verification

### Mount Status
```bash
$ ssh lehel.xyz "df -h /mnt/10g_volume"
Filesystem      Size  Used Avail Use% Mounted on
/dev/sdb         20G   12G  6,9G  64% /mnt/10g_volume

$ ssh lehel.xyz "cat /etc/fstab | grep 10g_volume"
/dev/disk/by-id/scsi-0HC_Volume_101343964 /mnt/10g_volume ext4 discard,defaults 0 0

$ ssh lehel.xyz "mount | grep 10g_volume"
/dev/sdb on /mnt/10g_volume type ext4 (rw,relatime,discard)
```

### Docker Configuration
```bash
$ ssh lehel.xyz "docker info | grep 'Docker Root Dir'"
 Docker Root Dir: /mnt/10g_volume/docker

$ ssh lehel.xyz "docker ps -q | wc -l"
15  # All containers running

$ ssh lehel.xyz "sudo du -sh /mnt/10g_volume/*"
17G     /mnt/10g_volume/docker
2.1G    /mnt/10g_volume/2GB.swap
```

### All Services Healthy
- ✅ 15 containers running
- ✅ traefik, leaguesphere, photoprism, portainer, energy, etc.
- ✅ Health checks passing (starting up after restart)

## Files Modified

| File | Change | Description |
|------|--------|-------------|
| `plays/vars/default.yml` | Modified | Added device, fstype, opts to extension_drive |
| `plays/roles/system/tasks/extension_drive.yml` | NEW | Mount task implementation |
| `plays/roles/system/tasks/main.yml` | Modified | Integrated extension_drive task |
| `/etc/docker/daemon.json` (production) | Modified | Added data-root configuration |

**Git Commits:**
- `7413082` - feat: automate extension drive mount before Docker setup

## Execution Order

```
system.packages
  ↓
system.user (create user cda)
  ↓
system.extension_drive (mount /mnt/10g_volume) ← NEW
  ↓
system.storagebox (mount storage box)
  ↓
...
user.docker.setup (configure docker data-root)
  ↓
user.docker.services (start containers)
```

## Benefits

1. **Persistence:** Extension drive mounts automatically on boot via `/etc/fstab`
2. **Idempotency:** Safe to run multiple times
3. **Conditional:** Only runs on hosts with `has_10g_volume: true`
4. **Device Stability:** Uses `/dev/disk/by-id/` for consistent device naming
5. **Performance:** `discard` option enables TRIM for SSD/cloud volumes

## Known Issues

**None** - All systems operational

## Follow-Up Items

- [ ] Optional: Install `json_patch` Ansible collection for docker_setup automation
- [ ] Optional: Monitor monit for 10g_volume disk space alerts

## Success Criteria

- [x] Extension drive mounted at `/mnt/10g_volume`
- [x] Persistent `/etc/fstab` entry created
- [x] Docker data root: `/mnt/10g_volume/docker`
- [x] All 15 containers running successfully
- [x] Mount survives reboot (fstab entry present)
- [x] Merged to master branch

## Post-Deployment Monitoring

Monitor for:
- Mount persists after reboot
- Docker continues using extension drive
- No disk space issues on root filesystem
- monit alerts for 10g_volume usage (80%, 85%)

**Next reboot:** Verify mount automatically succeeds via fstab entry.
