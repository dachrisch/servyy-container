#!/bin/zsh
set -x

# Pre-deployment check: Clean up stale mounts on servyy-test.lxd
echo "Checking for stale mounts on servyy-test.lxd..."
if ssh servyy-test.lxd "test -d /mnt/storagebox" 2>/dev/null; then
    # Check if mount is stale (directory exists but not properly mounted)
    if ! ssh servyy-test.lxd "timeout 2 ls /mnt/storagebox >/dev/null 2>&1"; then
        echo "Detected stale mount at /mnt/storagebox, cleaning up..."
        ssh servyy-test.lxd "sudo fusermount -u /mnt/storagebox 2>/dev/null || sudo umount -l /mnt/storagebox 2>/dev/null || true"
        echo "Stale mount cleaned up."
    fi
fi

ansible-playbook servyy.yml -i testing --skip-tags system.swap,ubuntu_pro "$@"
