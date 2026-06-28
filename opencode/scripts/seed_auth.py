#!/usr/bin/env python3
"""Seed the Antigravity (Google) OAuth credential into OpenCode's auth.json.

Reads the base64-encoded ``{"google": {...}}`` blob from the
OPENCODE_AUTH_GOOGLE_B64 environment variable and merges it into
``$AUTH_DIR/auth.json``. Idempotent: never clobbers a ``google`` entry that
OpenCode may have refreshed on a previous boot (the volume is persisted).

Prints ``seeded`` or ``present`` for the caller to log. Exits 0 on no-op.
"""
import base64
import json
import os
import sys

blob = os.environ.get("OPENCODE_AUTH_GOOGLE_B64")
if not blob:
    sys.exit(0)

auth_dir = os.environ.get("AUTH_DIR") or os.path.join(
    os.environ.get("HOME", "/root"), ".local", "share", "opencode"
)
path = os.path.join(auth_dir, "auth.json")

seed = json.loads(base64.b64decode(blob))

data = {}
if os.path.exists(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        data = {}

if "google" in data:
    print("present")
    sys.exit(0)

data.update(seed)
os.makedirs(auth_dir, exist_ok=True)
with open(path, "w") as fh:
    json.dump(data, fh)
os.chmod(path, 0o600)
print("seeded")
