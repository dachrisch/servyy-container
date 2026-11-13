# `bash` missing in the codey opencode container

**Date:** 2026-11-13
**Status:** ✅ Accepted — deployed to `codey.lehel.xyz` and verified
**Relates to:** [opencode/scripts/AGENTS.md](../opencode/scripts/AGENTS.md),
[history/2026-09-26_opencode-server-skills.md](2026-09-26_opencode-server-skills.md)

## Context

Sessions on `code.lehel.xyz` could not run any `#!/bin/bash` script. A real failure from the
session DB:

```text
CMD: .claude/skills/check-server-status/check-status.sh servy.lehel.xyz
OUT: env: can't execute 'bash': No such file or directory
     Exit code: 127
```

One session had already worked around it by hand ("the skill script couldn't run — no bash in
container"), which is exactly the kind of drift that should be fixed in the image instead.

Root cause: `opencode.web` runs the upstream **Alpine** image (`ghcr.io/anomalyco/opencode:2.3.0`,
`opencode v2.2.7`), where `/bin/sh` is BusyBox and nothing else is a shell. `opencode/scripts/startup.sh`
installed `git curl github-cli nodejs npm python3 py3-pip openssh-client-default git-crypt gettext`
(plus chromium) — never `bash`. `claude-hub/scripts/startup.sh` on the same host *does* install it,
which is why only this service was affected.

Evidence gathered before changing anything:

| Probe | Result |
|---|---|
| `which bash` / `ls /bin/bash` in `opencode.web` | not found |
| `apk info -e bash` | rc=1 (not installed) |
| `GET /api/config/shell` | only `/bin/sh` and `/bin/ash`, both `acceptable: true` |
| tool names in recent sessions | `shell` (1274 calls) — V2 has no `bash` tool, so "bash is inactive" was both a name and a binary problem |
| V1-era tool list in `docs/plans/2026-10-21-opencode-v2-upgrade.md` | still contained `bash`, hence the stale expectation |

So nothing was disabled by configuration: the binary simply did not exist, and OpenCode V2 names the
tool `shell`.

## Decision

Add `bash` to the `apk add` line in `opencode/scripts/startup.sh` and let the existing boot path
install it, rather than mounting a wrapper or rewriting every skill to POSIX `sh`. `startup.sh` runs on
every container start/recreate, so the package returns automatically after an image bump.

No `"shell": "/bin/bash"` config entry was added: with bash present, OpenCode already selects it for the
`shell` tool (verified below), so pinning it would only add a failure mode.

## Consequences

### Positive

- ✅ The agent's `shell` tool now runs **`/bin/bash`** instead of BusyBox `sh`.
- ✅ `#!/bin/bash` scripts — including the `check-server-status` skill — execute instead of exiting 127.
- ✅ `GET /api/config/shell` lists `/bin/bash` as an acceptable shell.
- ✅ Nothing manual: the package is reinstalled on every boot/recreate like the other dependencies.

### Negative / Tradeoffs

- ⚠️ ~1 MB in the image rootfs (not the persistent volume), re-downloaded on recreate.
- ⚠️ The `apk add` line is unguarded (`set -e`), so an apk failure at boot already fails the container;
  bash does not add a new failure mode, but it does enlarge that line.
- ⚠️ Skills may now *assume* bash on this host; anyone reusing them outside this container (e.g. on a
  `sh`-only host) still needs the POSIX path.

### Implementation Details

**Files modified:**
- `opencode/scripts/startup.sh` (MODIFY, line 22) — `bash` appended to `apk add`, with a comment
  pointing at this entry.

**Deploy:**

```bash
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
```

`changed=9, failed=0`. The compose file itself was unchanged, so the bind-mounted `startup.sh` was
synced by the role and the container was recreated on the deploy — which re-ran the boot script and
installed bash.

**Verification:**

```text
$ docker exec opencode.web sh -c 'bash --version | head -1'
GNU bash, version 5.3.9(1)-release (x86_64-alpine-linux-musl)

$ docker exec opencode.web sh -c 'curl -s -u opencode:$PW http://127.0.0.1:4096/api/config/shell'
[{"path":"/bin/sh","name":"sh","acceptable":true},
 {"path":"/bin/ash","name":"ash","acceptable":true},
 {"path":"/bin/bash","name":"bash","acceptable":true}]

$ docker exec opencode.web sh -c '.claude/skills/check-server-status/check-status.sh codey.lehel.xyz'
### codey.lehel.xyz ###  --- uptime/load --- ... (runs; previously exit 127)
```

End-to-end through the agent (throwaway session on codey, deleted afterwards), the `shell` tool
reported:

```text
shell=/bin/bash
/bin/bash
inner=bash
```

**Key learnings:**
1. "The `bash` tool is not active" was two facts: V2 renamed the tool to `shell`, *and* the Alpine
   image had no bash binary — checking only the config would have missed it.
2. `GET /api/config/shell` is the cheap authoritative probe for "which shell can the agent use";
   it needs Basic auth (`opencode:$OPENCODE_SERVER_PASSWORD`) and is only reachable inside the
   container (the authgate blocks it from outside).
3. Container health flaps as `unhealthy` right after a recreate: `startup.sh` (apk + pip installs) runs
   before `opencode serve`, so `/health` refuses connections until the boot finishes. It returns to
   `healthy` on the next 30 s check.

## Alternatives Considered

### Alt A: pin `"shell": "/bin/bash"` in `opencode.json.template`

Pros: explicit, no autodetection.
Cons: unnecessary once bash exists (OpenCode already picks it), and it turns a would-be fallback to
`sh` into a hard failure if the binary ever goes missing.
**Rejected**

### Alt B: rewrite the affected skills to POSIX `sh`

Pros: works on any host, no extra package.
Cons: bash is present on every other host in this fleet (claude-hub installs it explicitly), so this
would degrade the skills' quality to work around one container's gap.
**Rejected**

### Alt C: mount a bash static binary into the container

Pros: no apk dependency.
Cons: unmanaged binary, per-arch, no upstream security updates.
**Rejected**
