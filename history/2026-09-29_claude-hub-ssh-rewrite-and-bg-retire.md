# 2026-09-29 claude-hub: git over SSH, and task sessions dying while waiting on the user

Two bugs seen in dispatched session `5dc0038b` (leaguesphere PR #2029 review).

## Bug 1: `git fetch/push origin` fails in task sessions: FIXED

**Symptom:** `git ls-remote origin` → `error: cannot run ssh: No such file or directory`.

**Cause:** the `/root/dev` checkouts are on the `codey_dev_checkouts` volume, shared with
opencode. On each opencode boot, `opencode/scripts/provision-dev.sh` runs
`remote set-url origin git@github.com:<owner>/<repo>.git` on every repo. On each
claude-hub boot, `provision-repos.sh` sets them back to HTTPS, and `spinup-repo.sh` does
the same for the repos it dispatches. Whichever container booted last wins. On 2026-09-29
every repo except servyy-container had an SSH origin. Worktrees share their source repo's
config, so task sessions inherited the SSH origin. The claude-hub container has no `ssh`
binary and no key; it authenticates with `gh-cred-helper.sh` over HTTPS.

**Fix:** a new script, `claude-hub/scripts/configure-git.sh`, called from `startup.sh`,
holds all of claude-hub's global git config: identity, the credential helper,
`useHttpPath`, and now:

```
url.https://github.com/.insteadOf = git@github.com:
url.https://github.com/.insteadOf = ssh://git@github.com/
```

- This lives in claude-hub's own global config (`/root/.gitconfig` on the `claude_hub_root`
  volume), not in the shared checkouts. opencode keeps its SSH origins and its own reverse
  rewrite (https→ssh).
- git-crypt is not affected. It is a smudge/clean filter and does not depend on the transport.
- `insteadOf` covers both fetch and push. The script resets the key before adding the two
  values, so running it on every boot does not pile up duplicates.
- The `set-url` calls in `provision-repos.sh`/`spinup-repo.sh` are kept. They are harmless
  now, and removing them is out of scope. The fight over the remote URL is cosmetic from here on.

**Verified** (in the prod claude-hub container, against a throwaway `HOME`, so the live
config was not touched):
- `git ls-remote --get-url origin` in `/root/dev/dachrisch/leaguesphere` → `https://github.com/dachrisch/leaguesphere.git`
- `git ls-remote origin HEAD` → `ede3edf…`, authenticated through gh-cred-helper
- Running the script twice leaves exactly two `insteadOf` values.

**Tests:** the Molecule scenario `docker_service/gh-wrapper` (already in the CI matrix) now
installs and runs the real `configure-git.sh`, runs it again, and checks:
- exactly two `insteadOf` values after the second run
- the credential helper and `useHttpPath` are still set
- both SSH URL forms resolve to HTTPS
- the checkout's own `remote.origin.url` is unchanged

## Bug 2: a session that ends its turn with a question dies before the user answers: CLI BEHAVIOUR, workaround proposed

**What actually happens** (`~/.claude/daemon.log`):

```
06:07:20 binary ... changed (mtime changed) — self-restarting for upgrade
06:07:21 bg adopt: adopted=1 respawned=0 dead=0
06:09:21 bg retire 5dc0038b: idle-prompt, idle 2m [low memory]
06:09:26 idle 5s with no clients — exiting
```

The session is not killed by the reaper or by an idle timeout of the `--bg` service. The
Claude Code **daemon retires it under memory pressure**. From the 2.1.284 bundle
(`retireIfSettled` and the sweep):

- Low memory means `os.freemem() < tengu_bg_low_mem_mb`. That flag is server-side, default
  1024 MB. Codey has 2 GB RAM and about 750 MB available even while idle, so the daemon is
  **always** in low-memory mode. Each task session costs about 470 MB (claude ~385 MB +
  pty host ~85 MB).
- In low-memory mode, a worker counts as settled and gets retired after **60 s** with no
  input. That includes `state=blocked, tempo=blocked`, i.e. waiting on the user. Normally
  the grace is 1 h, or 8 h for Remote Control ("bridged") sessions.
- `pins.json` pins do not help. The sweep also retires pinned settled workers "as a last
  resort" when memory stays low, and on codey it always does.
- No local knob exists. `CLAUDE_INTERNAL_FC_OVERRIDES` exists, but the public build stubs
  out `getEnvironmentOverrides()` (it `return null`s), and `daemon.json`/settings have
  nothing for it.
- After the last worker is gone the transient daemon exits. Remote Control disconnects,
  and a reply sent from claude.ai is not delivered. The revive on 2026-09-29 confirmed this.

**Retire exemptions that the CLI supports:**
1. **An attached client** (`claude attach <id>`). Each one is another ~100 MB process, which
   makes the memory problem worse.
2. **A pending session cron.** The daemon never retires a worker whose `inFlight.kinds`
   contains `session_cron`, even under low memory. It checks this before the pinned
   last-resort. The CLI's own hook schema describes `session_crons` as "Session-scoped cron
   tasks (CronCreate, ScheduleWakeup, /loop) that will wake this session later". A
   **one-shot `CronCreate` scheduled well into the future** costs no tokens until it fires
   and keeps the session connected.

**Proposed workaround (not in this PR):** add this rule to the task-session `CLAUDE.md`
that `vendor/skills/spinup-session/scripts/spinup-session.mjs` writes:

> Before you end a turn with a question to the user (or `AskUserQuestion`), schedule a
> one-shot keepalive: `CronCreate(recurring: false, cron: <about 24 h from now>, prompt:
> "keepalive: if your last question is still unanswered, re-ask it in one line and
> schedule the next keepalive; otherwise do nothing")`. Without it, the Claude daemon
> retires the session about 60 s after your turn ends (low memory on codey), and the
> user's reply never reaches you. Delete it with `CronDelete` once the user has answered.

It was left out of this PR because the auto-mode classifier running the task session
refused to read or edit the session-instruction template (it classed that as
"self-modification"). A human needs to apply it. The reaper does not interfere: it already
never parks `waiting_on_user` sessions.

**Trade-off:** every session kept alive holds about 470 MB on a 2 GB host with 6 GB swap.
Several waiting sessions will swap. **The real fix is RAM:** with ≥ 4 GB on codey, free
memory stays above 1 GB and the CLI's normal 8 h grace for Remote Control sessions applies.
No workaround is needed then.

**Auto-update:** the CLI updated itself in place (npm-global, 2.1.283 → 2.1.284). The daemon
self-restarted and **re-adopted** the live worker (`adopted=1`), so the update did not kill
the session. While npm swapped the `/usr/local/bin/claude` symlink, though, CLI calls hit
`ENOENT`, which explains the reaper's `agents_failed: spawnSync /usr/local/bin/claude ENOENT`.
`DISABLE_AUTOUPDATER=1` is now set in `claude-hub/docker-compose.yml`. `startup.sh`'s
`npm install -g` at container boot is the only upgrade path, so the CLI version changes on
each redeploy/restart.

## Not verified here
- **servyy-test.lxd:** not reachable from inside the claude-hub container (no ssh, lxc or
  ansible). Needs to be run from a workstation:
  `cd scripts && ./setup_test_container.sh && cd ../ansible && ./servyy-test.sh --tags user.docker.claude-hub`,
  then `docker exec claude-hub.hub sh -c 'cd /root/dev/dachrisch/leaguesphere && git ls-remote origin HEAD'`.
- **The keepalive exemption, end to end:** not verified. A throwaway `--bg` session was
  blocked by the auto-mode classifier, so this is based on reading the code, not a live run.
