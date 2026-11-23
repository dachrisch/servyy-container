#!/bin/zsh
# Idempotent setup for the runny-test VM (the rootless-runner rehearsal host).
# Launches an Ubuntu 26.04 VM shaped like runny (2 vCPU / 1 GiB) on the local
# lxd, injects ~/.ssh/id_rsa.pub into the default `ubuntu` user, and prints the
# IP. Run with `-x` to tear it down.
#
# Unlike setup_test_container.sh (servyy-test), this is a VM, not a privileged
# container: it exists to rehearse AppArmor and "no root-run Docker", which a
# privileged LXD container cannot prove. See docs/plans/2026-11-23_runny-docker-trust.md.
set -e
instance=runny-test
hostname="${instance}.lxd"
# runny/servy/codey are Ubuntu 26.04 (resolute); the rehearsal VM matches them.
UBUNTU_VERSION="${UBUNTU_VERSION:-26.04}"
PUBKEY="${PUBKEY:-$HOME/.ssh/id_rsa.pub}"
POOL="${RUNNY_TEST_POOL:-runner}"   # dir pool that also backs the old git-runner profile

if [[ "$1" = '-x' ]]; then
  echo "removing [$instance] from lxd"
  lxc stop "$instance" 2>/dev/null || true
  lxc delete "$instance" 2>/dev/null || true
  lxc profile delete "$instance" 2>/dev/null || true
  exit 0
fi

# Idempotent: leave an already-running instance alone.
if lxc info "$instance" >/dev/null 2>&1 && lxc info "$instance" | grep -q 'Status: RUNNING'; then
  echo "[$instance] already running"
  host "$hostname" 2>/dev/null || true
  lxc list "$instance"
  exit 0
fi

# Profile: bridged NIC + root disk on the VM pool. No cloud-init here — the
# ssh key is set on the instance below so the profile stays machine-neutral.
if ! lxc profile get "$instance" name >/dev/null 2>&1; then
  echo "creating profile [$instance]"
  lxc profile create "$instance"
fi
echo "updating profile [$instance]"
cat > "/tmp/${instance}.yaml" <<EOF
config:
  cloud-init.user-data: |
    #cloud-config
    write_files:
      - path: /etc/apt/apt.conf.d/99force-ipv4
        content: 'Acquire::ForceIPv4 "true";'
        permissions: '0644'
      - path: /etc/apt/sources.list.d/ubuntu.sources
        permissions: '0644'
        content: |
          Types: deb
          URIs: https://mirror.netcologne.de/ubuntu
          Suites: resolute resolute-updates resolute-backports
          Components: main universe restricted multiverse
          Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

          Types: deb
          URIs: https://mirror.netcologne.de/ubuntu
          Suites: resolute-security
          Components: main universe restricted multiverse
          Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        groups: users, admin
        shell: /bin/bash
        ssh_authorized_keys:
          - $(cat "$PUBKEY")
devices:
  eth0:
    name: eth0
    nictype: bridged
    parent: lxdbr0
    type: nic
  root:
    path: /
    pool: $POOL
    type: disk
    size: ${RUNNY_TEST_DISK:-20GiB}
EOF
cat "/tmp/${instance}.yaml" | lxc profile edit "$instance"

if ! lxc info "$instance" >/dev/null 2>&1; then
  echo "launching VM [$instance] (Ubuntu $UBUNTU_VERSION, 2 vCPU / 1 GiB)"
  lxc launch ubuntu:"$UBUNTU_VERSION" "$instance" \
    --vm \
    -p "$instance" \
    -c limits.cpu=2 \
    -c limits.memory=1GiB
fi

# Wait for the lxd DNS name (DHCP lease registered on first boot).
echo -n "waiting for [$hostname] to resolve..."
retries=60
while ! host "$hostname" >/dev/null 2>&1; do
  printf .
  ((retries--))
  [[ $retries -gt 0 ]] || { echo " FAILED"; lxc list "$instance"; exit 1; }
  sleep 2
done
echo " done"
host "$hostname"

# Wait for ssh (cloud-init applies the key on first boot).
echo -n "waiting for ssh on ubuntu@$hostname..."
retries=60
while ! ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o BatchMode=yes "ubuntu@$hostname" true 2>/dev/null; do
  printf .
  ((retries--))
  [[ $retries -gt 0 ]] || { echo " FAILED"; lxc list "$instance"; exit 1; }
  sleep 2
done
echo " done"

lxc list "$instance"
