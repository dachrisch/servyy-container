# 2026-10-14 — opencode service: chrome-devtools MCP runs headless (server-side recording)

## Goal (issue dachrisch/servyy-container#213)

Make the `chrome-devtools` MCP on the server-side opencode service
(`codey.lehel.xyz`, container `opencode.web`) run **headless** so LeagueSphere's
`record-tutorial` skill can record tutorial videos unattended, server-side,
instead of on a developer's desktop. Previously the server shipped **no**
`chrome-devtools` MCP at all (only `circleci` + `docstash`), and the local dev
box runs it headful (`npx chrome-devtools-mcp@latest`) which takes over the real
desktop and caps the viewport.

## Change

Added a `chrome-devtools` MCP entry to
`opencode/scripts/opencode.json.template` (rendered to
`/root/.config/opencode/opencode.json` at container boot by `startup.sh`
via `envsubst`). The Ansible role already copies the template (task "Deploy
OpenCode config template"), so no role change was needed.

Command:

```
npx -y chrome-devtools-mcp@latest \
  --headless --viewport 1920x1080 --isolated \
  --executablePath /usr/lib/chromium/chromium \
  --chrome-arg=--no-sandbox \
  --chrome-arg=--disable-dev-shm-usage \
  --no-usage-statistics
```

### Why each non-obvious flag (verified live in the container)

- `--executablePath /usr/lib/chromium/chromium` — chrome-devtools-mcp 1.10.x
  defaults to the system "stable" channel at `/opt/google/chrome/chrome`, which
  does not exist here. We use **Alpine's `chromium` apk**. We point at the
  **real binary**, not the `/usr/bin/chromium` launcher: the Alpine launcher
  re-injects `--user-data-dir=$HOME/.config/chromium` when running as root,
  which would defeat `--isolated` and leave a shared persistent profile behind.
  (Chromium is now installed by `startup.sh` — see "Base image has no browser".)
- `--chrome-arg=--no-sandbox` — the container runs as **root**; Chrome refuses
  to start as root without it (`crbug.com/638180`). Without this the browser
  dies at launch.
- `--chrome-arg=--disable-dev-shm-usage` — Docker gives the container the
  default 64 MB `/dev/shm`; Chrome is known to crash on it under load. Avoids
  needing a `shm_size` bump on the compose service.
- `--no-usage-statistics` — it is a shared always-on server; opt out of sending
  inspected-page data to Google (the banner else warns it is collected).

### Base image has no browser

`ghcr.io/anomalyco/opencode:latest` does **not** ship a browser. Verified for
both current digests in use (`543fe6b1…` on codey, `b3ce2a73…` on servyy-test):
no chromium on PATH, no `/usr/lib/chromium/chromium`, empty puppeteer cache.
Without a browser the MCP fails at launch with "Could not find Google Chrome
executable for channel 'stable'". Relying on the image to provide one would
break on any recreate.

Fix: `opencode/scripts/startup.sh` now ensures chromium is present at boot
(guarded `apk add --no-cache chromium` → `/usr/lib/chromium/chromium`). The
guard makes it idempotent (no-op when already present) and non-fatal (a
transient apk failure logs a warning instead of killing the boot).

## Profile strategy (issue acceptance: pick one + note it)

**Chosen: `--isolated` (throwaway profile).**

- `--isolated` gives every browser launch a fresh temporary user-data-dir that
  is cleaned up when the browser closes.
- **Why not a persistent/seeded profile:** on this server the chrome-devtools
  MCP is shared by *every* session on the opencode instance (the issue's own
  caveat). A single persistent profile would be shared by all of them —
  concurrent sessions contend for the same profile lock (Chrome refuses a
  second instance on one profile dir) and unrelated sessions bleed
  cookies/logins into each other. `--isolated` actually *mitigates* the shared-
  browser caveat: each session gets a clean, independent browser.
- **Cost:** no persisted logins, so a session that needs to be authenticated
  must log in each run. This is fine for `record-tutorial`: its step 0 logs into
  `demo.leaguesphere.app` with the documented public demo credentials
  (`admin@demo.local` / `DemoAdmin123!`) on every run, so nothing depends on a
  persisted session.
- If a future workflow genuinely needs a warm, logged-in browser, seed a
  persistent profile instead (drop `--isolated`, add `--userDataDir <path>` on
  the `opencode_root` volume) — or, better, scope chrome-devtools to a dedicated
  recording service so it stops being shared by every session.

## Files changed

- `opencode/scripts/opencode.json.template` — new `chrome-devtools` MCP entry.
- `opencode/scripts/startup.sh` — install chromium at boot if missing.
- `history/2026-10-14_opencode-chrome-devtools-headless.md` (this file).

No Ansible or compose change: the config template and startup script were already
deployed and run at boot.

## Verification

Live against the running `opencode.web` on `codey.lehel.xyz` (image
`ghcr.io/anomalyco/opencode:latest`, chrome-devtools-mcp 1.10.1, Alpine
chromium 152):

- MCP handshake + `tools/list` OK (`chrome_devtools` server 1.10.1).
- `navigate_page` → `https://example.com`, `take_screenshot` returns an image
  (133 kB) — Chrome launches headless, no display needed.
- `navigate_page` → `https://demo.leaguesphere.app`, `take_screenshot` returns an
  image (197 kB) — the real recording target renders headless in-container.
- Confirmed failure modes without the flags: no `--executablePath` → "Could not
  find Google Chrome executable for channel 'stable'"; no `--no-sandbox` →
  "Chrome does not start as root". Both fixed by the command above.
- servyy-test.lxd (image `b3ce2a73…`, no chromium): reproduced the
  "Could not find Google Chrome" failure, then proved the fix both ways — a
  pristine throwaway container from the image installs chromium via
  `apk add --no-cache chromium` and yields a working
  `/usr/lib/chromium/chromium`, and the reconfigured `opencode.web` navigated
  `https://demo.leaguesphere.app` and returned a screenshot (197 kB) fully
  headless.
- `ansible-playbook servyy.yml --syntax-check -i testing` and the repo
  validators run before deploy.

## Impact / rollback

- Enables `record-tutorial` (and any browser-driving skill) on the server.
- Adds a headless, throwaway-profile browser to **every** opencode session on
  the instance — see the caveat above.
- Rollback: remove the `chrome-devtools` entry from
  `opencode/scripts/opencode.json.template` and redeploy
  (`--tags user.docker.opencode`), or restart after editing the rendered
  `opencode.json` on the host.

## Follow-up

- Chromium install adds ~300 MiB to the (ephemeral) container rootfs and is
  re-downloaded on every container recreate; codey's root disk is ~89% full
  (~3 GiB free), so watch this. If it becomes a problem, bake chromium into the
  base image instead, or switch to the lighter `chromium-headless-shell` apk
  (also verified working with chrome-devtools-mcp — 188 MiB vs 305 MiB, and
  since the server always runs `--headless`, nothing is lost).
- Consider scoping the recording browser to a dedicated service if it starts
  interfering with interactive sessions.
