# atuin: the role could never upgrade it, and its login now breaks the play

**Date:** 2026-10-29
**Status:** ✅ Fixed, deployed to `servy.lehel.xyz` and `codey.lehel.xyz` (both on 18.24.3)
**Fixes:** #233

## Context

`ansible/plays/roles/user/tasks/atuin.yml` installed atuin **only when it was missing**:

```yaml
- name: Check if atuin is installed
  shell: "atuin -V"
...
  when: autin_version.rc != 0
```

So each host froze at whatever version it first received — `servy` at 18.16.1 (May), `codey` at
18.20.1 (August) — while upstream shipped **18.24.3**. Nothing else upgrades them: these are
cargo-dist installs under `~/.atuin/bin`, the `atuin-update` helper is no longer published
upstream, and `update_check = true` only prints a notice.

The bigger problem was the login task. It ran unconditionally, and since 18.24 an
`atuin login` on a legacy sync session no longer says "already logged in" — it starts the Hub
auth migration against the live API and aborts the play:

```
You have a legacy sync session. Continuing login to upgrade to full Hub authentication.
ERROR error=invalid credentials
```

That made every `--tags user.atuin` run fail, i.e. the bug blocked its own fix.

## Decision

**Upgrade by version, not by presence.** Resolve the wanted version (pinned `atuin_version` or
GitHub's `releases/latest`), read the installed one, and run the official cargo-dist installer
only when they differ. `ATUIN_NO_MODIFY_PATH=1` plus `--no-modify-path` keeps the installer out
of `.bashrc`/`.profile` (they already source `~/.atuin/bin/env`); the env var is the modern
spelling, the flag is deprecated but still needed for pinned older releases. The installer is
downloaded with `get_url` into an ansible-managed tempfile and executed via `argv`, so no shell
quoting is involved.

**A failed lookup must not fail the play.** `uri` runs with `failed_when: false`; a 403 (rate
limit) or an offline host warns and keeps the current binary.

**Gate the login.** `atuin status | grep '^Username: '` decides: a host with a session skips
login entirely, and `Sync` follows only a fresh login. Converting a legacy session to Hub auth
is a deliberate interactive step and must never be automated.

**Secrets hygiene.** The login passes values through `argv` with `| trim`. The vaulted password
carried literal shell quotes (`"'$3b6X…'"`) which only worked because a `shell:` command let the
shell strip them — with `argv` they would have been sent verbatim. The value is now stored
unquoted; its effective content is unchanged (asserted when editing). The now-unused `atuin.url`
was dropped, `atuin_version: latest` added.

**Home directory.** `ansible_facts['user_dir']` resolves to `/root` in this play set (facts are
gathered as root, the tasks run as `create_user`), which is why the first deploy failed with
"Unable to change directory". The home is now read from `getent passwd {{ create_user }}`.

## Consequences

### Positive

- Both hosts are current (18.24.3) and will track upstream by default
- The play is a two-run idempotent no-op, and pinning works
- No more Hub-migration attempt, so a provision cannot fail on atuin
- The orphaned `atuin-update` binary is removed from older installs

### Negative / Tradeoffs

- `atuin_version` lives in `secrets.yml` (as the issue asked), so the pin is only readable with
  git-crypt unlocked — a version is not a secret and `vars/default.yml` would be the more
  natural home
- The installer is fetched from GitHub at deploy time; an offline host keeps its version and
  warns, rather than failing

### Known Issues / Open Findings

- The `user` role's molecule scenarios do not converge `atuin.yml`, so this path is covered by
  `--syntax-check` plus two real deploys, not by a test. An offline-safe test would need a
  stubbed installer.

## Verification

```
# first run upgrades, second is a no-op
servy: 18.16.1 → 18.24.3   (changed=4)   then changed=0
codey: 18.20.1 → 18.24.3                 then changed=0

atuin --version            → 18.24.3 on both
atuin status | grep -c ^Username:  → 1 on both (still logged in, no Hub migration)
grep -c atuin/bin/env ~/.bashrc ~/.profile → 1, 1 (installer did not touch profiles)
~/.config/atuin/atuin-receipt.json → 18.24.3
~/.atuin/bin/atuin-update → absent on both
/usr/bin/atuin → /home/cda/.atuin/bin/atuin (root-owned, unchanged)
-e atuin_version=18.24.3 → changed=0 and no GitHub API call
```
