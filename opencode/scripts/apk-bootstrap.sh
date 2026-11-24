#!/bin/sh
# Idempotent Alpine package bootstrap for the opencode container.
#
# Kept separate from startup.sh so the boot contract can be tested with a stub
# `apk` (see opencode/tests/test_apk_bootstrap.sh). Runs on every boot.
set -e

# Overridable for tests only; production uses the apk in the image.
APK_BIN=${APK:-apk}
# openssh-client-default, NOT the `openssh` meta: the meta pulls openssh-server,
# i.e. the sshd that briefly ran in this container without anyone starting it.
# The base image ships no OpenSSH at all, so installing the meta was the only
# thing that put sshd on the filesystem. The client stays: `ssh` for git/github,
# `ssh-keyscan` for known_hosts, `ssh-keygen` for commit signing.
# bash: the base image is Alpine/BusyBox (only /bin/sh), so `#!/bin/bash` skill
# scripts would die with exit 127 without it -- see
# history/2026-11-13_opencode-container-bash.md.
PACKAGES="git curl github-cli nodejs npm python3 py3-pip openssh-client-default git-crypt gettext bash"

echo "📦 [Startup] Installing system packages..."

# Repair the apk database BEFORE installing anything. An interrupted transaction
# can leave two installed packages claiming the same file (codey, 2026-11-24:
# python3-3.14.10-r1 vs python3-ndbm-3.14.10-r2 over _dbm...so, after Alpine
# 3.24 split that module out). `apk add` then exits 1 with only a bare
# "1 error; ..." summary, and startup.sh's `set -e` turns it into a restart loop.
# `apk fix --force-overwrite` clears the conflict, and is a ~0.7 s no-op on a
# healthy database. Guarded so an apk failure can never abort the boot on its own.
if "$APK_BIN" fix --force-overwrite >/dev/null 2>&1; then
    echo "📍 [Startup] apk database checked"
else
    echo "⚠️ [Startup] apk database repair failed (continuing)"
fi

if ! "$APK_BIN" update; then
    echo "⚠️ [Startup] apk update failed (continuing)"
fi

if "$APK_BIN" add $PACKAGES; then
    echo "📍 [Startup] system packages ready"
else
    echo "⚠️ [Startup] system package install failed; retrying after forced repair..."
    if "$APK_BIN" fix --force-overwrite >/dev/null 2>&1 && "$APK_BIN" add $PACKAGES; then
        echo "📍 [Startup] system packages ready (after repair)"
    else
        echo "⚠️ [Startup] system packages unavailable; continuing with image tooling"
    fi
fi

:
