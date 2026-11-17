#!/bin/sh
# Install graphify on architectures that have no prebuilt wheels (aarch64/musl).
#
# Why this is not just `pip install graphifyy`:
#
#  1. The core `tree-sitter` package publishes NO musllinux aarch64 wheel at any
#     version — x86_64 has `musllinux_1_2_x86_64`, aarch64 only has glibc
#     (manylinux) wheels that Alpine cannot use. It is a Rust extension, so it
#     must actually be compiled.
#  2. pip prefers the newest sdist over an older wheel. Most language packs do
#     have an aarch64 musl wheel, but only on older versions, so pip would
#     otherwise pick a newer sdist and try to compile it. That fails on several
#     grammars with:
#         tsx/src/parser.c:1:10: fatal error: tree_sitter/parser.h: No such file
#     because tree-sitter >= 0.25 no longer ships those C headers. Forcing
#     --only-binary makes pip backtrack to the versions that have a wheel.
#  3. graphifyy itself is installed with --no-deps, because its tighter pins
#     (e.g. tree-sitter-typescript<0.25) would drag the sdists back in. Its
#     remaining deps are pure-python or wheel-only.
#
# The result lands in /root/.graphify-pkgs, which is on the persistent volume,
# and docker-compose.yml puts it on sys.path via PYTHONPATH. So this runs once
# per host, not per boot.
set -u

DEST=/root/.graphify-pkgs

if PYTHONPATH="$DEST" python3 -c 'import graphify' 2>/dev/null; then
    echo "📍 [graphify] already installed in $DEST"
    exit 0
fi

if [ "$(uname -m)" = "x86_64" ]; then
    # Not our problem here: every dependency ships a musllinux_1_2_x86_64 wheel.
    # Still installed into $DEST rather than the image rootfs, so it survives
    # container recreates instead of re-running pip (~40s) on every boot.
    echo "🕸️ [graphify] installing from wheels (x86_64)..."
    python3 -m pip install --target "$DEST" --break-system-packages --quiet graphifyy \
        && PYTHONPATH="$DEST" python3 -c 'import graphify' 2>/dev/null \
        && echo "📍 [graphify] installed into $DEST ($(du -sh "$DEST" 2>/dev/null | cut -f1))" \
        || { echo "⚠️ [graphify] install failed"; exit 1; }
    exit 0
fi

echo "🕸️ [graphify] building for $(uname -m) — one-off, takes a couple of minutes"
if ! apk add --no-cache rust cargo build-base python3-dev >/tmp/graphify-apk.log 2>&1; then
    echo "⚠️ [graphify] build toolchain unavailable, skipping"
    tail -3 /tmp/graphify-apk.log 2>/dev/null
    exit 1
fi

# Only the packs that publish an aarch64 musl wheel. Skipped for lack of one:
# kotlin, objc, swift, lua, powershell, elixir, fortran, verilog, zig, groovy.
# graphify still imports and parses the languages below.
WHEEL_PACKS="python javascript typescript go rust java c cpp ruby c-sharp json julia scala php bash"
for p in $WHEEL_PACKS; do
    python3 -m pip install --target "$DEST" --break-system-packages --quiet \
        --only-binary=:all: "tree-sitter-$p<0.26,>=0.23" 2>/dev/null || true
done

# Core tree-sitter: no aarch64 musl wheel exists, so compile it (Rust/maturin).
if ! python3 -m pip install --target "$DEST" --break-system-packages --quiet \
        "tree-sitter<0.26,>=0.25"; then
    echo "⚠️ [graphify] core tree-sitter failed to build"
    exit 1
fi

python3 -m pip install --target "$DEST" --break-system-packages --quiet \
    --no-deps graphifyy 2>/dev/null || true
python3 -m pip install --target "$DEST" --break-system-packages --quiet \
    --only-binary=:all: networkx numpy rapidfuzz pyyaml 2>/dev/null || true

if PYTHONPATH="$DEST" python3 -c 'import graphify' 2>/dev/null; then
    echo "📍 [graphify] installed into $DEST ($(du -sh "$DEST" 2>/dev/null | cut -f1))"
else
    echo "⚠️ [graphify] import still failing after install"
    exit 1
fi
