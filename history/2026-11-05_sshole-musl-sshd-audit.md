# 2026 musl/OpenSSH "sshole" audit — nothing exposed, opencode stops shipping sshd

**Date:** 2026-11-05
**Status:** ✅ Audited all hosts + router + containers; opencode deployed to `codey.lehel.xyz`
**Relates to:** `2026-10-09_host-hardening-sshd-fix.md`, `2026-10-08-host-hardening-p6.md`

## Context

[sshhole.com](https://sshhole.com/) (found by Ozgun Kultekin, Nov 2026) documents an
OpenSSH auth bypass that needs **five** conditions at once:

1. sshd on **musl** (Alpine, OpenWrt, buildroot, yocto),
2. **no PAM**,
3. `PasswordAuthentication` enabled (the default),
4. an account whose shadow field is a bare `*`,
5. **another** account with a real hash — sshd borrows its salt, and only then does
   `crypt()` fail and return `"*"`, which compares equal to the stored `"*"`.

When all five hold, that `*` account takes **any** password of 257–1024 bytes. The
mechanism: musl's `crypt()` returns `"*"` instead of `NULL` on failure (2012), and its
SHA-512 backend rejects keys > 256 bytes (2012, DoS cap). Upstream fix: **openssh 10.6p2**.
Alpine moved `main/openssh` to 10.6_p2 on 2026-11-05 (d482fb5012fb), but **v3.24 — the
repo the opencode image tracks — still ships 10.3_p1-r2**, so `apk upgrade` does not fix it.

## Decision

**Hosts, LXD and the router: no change** — none of them can meet condition 1 or 2.

| Target | libc | PAM | sshd | Password auth | Verdict |
|---|---|---|---|---|---|
| `servy.lehel.xyz` (Ubuntu 26.04) | glibc | yes | OpenSSH_10.2p1 | no | immune |
| `codey.lehel.xyz` (Ubuntu 24.04) | glibc | yes | OpenSSH_9.6p1 | **yes** | immune (glibc + PAM) |
| `servyy-test.lxd` (Ubuntu 26.04) | glibc | yes | OpenSSH_10.2p1 | no | immune |
| `home-test` (LXD, Ubuntu 22.04) | glibc | yes | sshd on `0.0.0.0:22` | no | immune |
| workstation (Ubuntu 26.04) | glibc | yes | sshd on `:22` | no | immune |
| FritzBox 3490 + freetz-ng | **uClibc 1.0.31** | no PAM (irrelevant) | **dropbear 2026.94** | **yes**, root-only | immune |
| 40+ containers | mixed | — | **no sshd process, no `:22` published** | — | not exposed |

The router is immune by code, not just by libc: dropbear's
`DROPBEAR_MAX_PASSWORD_LEN` is **100** (`src/sysoptions.h`), and
`src/svr-authpasswd.c:68,83` refuses anything longer **before** `crypt()` is called, so the
257–1024-byte payload never reaches the buggy path. Live banner from `192.168.178.1:22`:
`SSH-2.0-dropbear_2026.94`.

**opencode: stop installing the server.** `opencode/scripts/startup.sh` added `openssh`
(the *meta* package) on 2026-02-17 (d0d95b7), so every container boot installed
`openssh-server`, i.e. a musl, no-PAM sshd. It never bound `:22` and the container had no
account with a real hash, so it was never exploitable — but it was one `rc-service sshd
start` plus a published port away, in a container where agents run as root. The upstream
image ships **no** OpenSSH at all (its `/etc/apk/world` is just alpine-baselayout,
alpine-keys, apk-tools, busybox, …), so our own `apk add` was the sole source.

## Consequences

### Positive

- ✅ sshd is gone at the source: `openssh-client-default` (ssh/scp/sftp/ssh-keygen) keeps
  git-over-SSH, `ssh-keyscan` and commit signing working, without the server.
- ✅ A guarded `apk del openssh` also purges sshd from containers created before this
  change (`apk del openssh-server` alone is refused while the meta depends on it).
- ✅ The audit is documented with per-host evidence, so "are we affected?" is answerable
  from the repo instead of by re-checking five hosts.
- ✅ `opencode/docker-compose.yml` now tolerates both `/health` generations (see below).

### Negative / Tradeoffs

- ⚠️ The healthcheck had to be relaxed from "must be 200" to "200 or 401" for `/health`;
  liveness is now "the HTTP server answers", with the real assertion being that
  unauthenticated `/api/info` is still 401.
- ⚠️ The image's `latest` tag is a moving target: `/health` auth behaviour changed
  between 2.1.2 and 2026-10-28 without a version bump we control.

### Implementation Details

**Files modified**

- `opencode/scripts/startup.sh` — `openssh` → `openssh-client-default`; new step 1a that
  purges `openssh-server` if present (guarded, `set -e`-safe, idempotent).
- `opencode/scripts/AGENTS.md` — "no SSH daemon in this container" rule for agents.
- `opencode/docker-compose.yml` — healthcheck: `/health` accepts `200|401`,
  `/api/info` must be `401`.

**Commits**

- `ede3d3c` fix(opencode): install only the ssh client, never openssh-server
- `3b2dcf8` fix(opencode): accept the newer image's 401 on /health

**Testing & Verification**

- Router: `getent hosts fritz.box`; raw banner over `/dev/tcp/192.168.178.1/22`;
  `ssh root@192.168.178.1` → `ldd`-less MIPS/uClibc 1.0.31 (`/lib/ld-uClibc-1.0.31.so`),
  `ps w` → `dropbear -p 22`, `DROPBEAR_MAX_PASSWORD_LEN 100` in the 2026.94 source
  freetz-ng actually built.
- Every container on all three Docker hosts: `docker top <c> | grep -E 'sshd|dropbear'`
  → no matches; `docker ps --format` → no `:22->` publishing. Only `opencode.web` (codey
  and servyy-test) and `git.www` even had an sshd binary; `git.www` is glibc.
- Pristine-image check of the new package line, run against
  `ghcr.io/anomalyco/opencode:2.1.2` with `--entrypoint sh`:
  `apk add ... openssh-client-default ...` → `/usr/sbin/sshd` absent, `ssh -V` works.
- Live container after recreation: `sshd-absent`, `cat /etc/apk/world | grep ssh` →
  `openssh-client-default` only, `ssh -o BatchMode=yes -T git@github.com` →
  `Hi dachrisch! You've successfully authenticated`, `docker ps` → `Up (healthy)`.
- `/health` behaviour compared on both images with `OPENCODE_SERVER_PASSWORD` set:
  2.1.2 → `200`, `latest` (f4cfe16) → `401`; `/api/info` → `401` on both.

**Key Learnings**

1. **The vulnerable sshd was self-inflicted.** The upstream image has no OpenSSH; a
   `apk add openssh` (meta) in our boot script pulled `openssh-server` on every boot
   since 2026-02-17. Package *names* matter: the meta is a server install.
2. **dropbear caps passwords at 100 bytes**, so the "long password" class of musl bugs
   cannot reach it — a stronger immunity argument than "it's not OpenSSH".
3. **`apk del openssh-server` is a no-op while `openssh` depends on it**; deleting the
   meta is what works, and only if the client was added to the world first (otherwise
   `apk del` purges the client with it).
4. **A floating `latest` tag can flip a healthcheck**: the same healthcheck that was
   green for months started failing because `/health` began requiring auth.

### Known Issues & Limitations

- `servyy-test.lxd` runs the same `opencode.web` image with the old script; it picks up
  the fix on its next deploy (the repo change is shared).
- A full `--tags user.docker.opencode` run currently dies in the role's Vaultwarden
  pushes: `bw unlock` with the 12-byte `~/.ssh/vw.key` fails, and those tasks run before
  the deploy tasks. The three files were therefore deployed with `ansible ... -m copy`
  using the role's exact source/dest/mode. The stale vault credential is unrelated to
  this change but blocks the normal deploy path.
- The healthcheck still routes through `grep -qxE`, so a server that answers `/health`
  with a 401 *and* stops authenticating would pass the first assertion — the
  `/api/info == 401` assertion is what makes that detectable, and it cannot distinguish
  "auth enforced" from "auth broken".
