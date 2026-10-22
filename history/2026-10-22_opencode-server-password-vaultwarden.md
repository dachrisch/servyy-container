# ADR: Back up the OpenCode server password to Vaultwarden

**Date:** 2026-10-22
**Status:** Accepted
**Relates to:** `history/2026-10-22_opencode-v2-upgrade.md`

## Context

`OPENCODE_SERVER_PASSWORD` (`secrets.yml` → `opencode.server_password`) existed only in two
places: the git-crypt encrypted `ansible/plays/vars/secrets.yml`, and the rendered
`opencode.env` on each host. The `vaultwarden` role already mirrors three OpenCode
credentials — the API key (`opencode_authgate.yml`), the GitHub SSH key (role task +
handler), and the YouTube OAuth token (role task) — but not this one.

The gap became materially worse with the V2 upgrade: V2 replaced the V1 basic-auth web UI
with a static client shell that must be paired, and its pairing screen offers **"Use
password"** as the fallback when `opencode pair` cannot be run (headless host, expired 5-minute
link). The server password is therefore now the routine browser/app login for
`code.lehel.xyz`, not just an API credential — and losing it means losing access to the
operator UI until the git-crypt'd secrets file is decrypted.

## Decision

Push it to Vaultwarden on every deploy, from the `opencode` role
(`ansible/plays/roles/opencode/tasks/main.yml`), reusing the shared
`roles/vaultwarden/tasks/push_items.yml` wrapper.

- Item name `opencode - server password` — no host suffix, because
  `opencode.server_password` is a single global secret shared by every host running opencode
  (codey, servyy-test), unlike the per-host API key item.
- Not handler-driven: the password has no change event to react to. `push_items.yml` is
  idempotent (creates when missing, updates when the value changed, reports unchanged
  otherwise), so an unconditional push on every deploy is safe.
- Gated on `inventory_hostname == 'codey.lehel.xyz'` like the neighbouring YouTube OAuth
  push, so the item is created once from the canonical host.

## Consequences

### Positive

- ✅ The one credential a human needs to get back into the web UI is recoverable from
  Vaultwarden, not only from a git-crypt'd file on one developer machine.
- ✅ No new mechanism: same role, same wrapper, same idempotency and `bw lock` handling as
  the other three OpenCode items.
- ✅ Rotations propagate: changing `opencode.server_password` and redeploying updates the
  vault item and `opencode.env` in the same run (they cannot silently diverge).

### Negative / tradeoffs

- ⚠️ One more `bw` unlock/API login per deploy of the role (~4 CLI calls, `run_once`).
- ⚠️ Item notes are the only place documenting that the value doubles as the UI login;
  keep them accurate if the auth model changes again.
- ⚠️ A rotation still signs out every paired web/app session (30-day cookies) — the vault
  backup makes the new value findable, it does not make the rotation seamless.

### Implementation Details

**Files changed:**

- `ansible/plays/roles/opencode/tasks/main.yml` — new task
  `Back up opencode server password to Vaultwarden` after the YouTube OAuth push.
- `history/2026-10-22_opencode-server-password-vaultwarden.md` (NEW) — this ADR.

**Verification:**

- `yamllint` on the role file: no new findings (the one pre-existing long-line warning on
  the YouTube notes line is unchanged from HEAD).
- `ansible-lint --show-relpath` on the file: `Passed: 0 failure(s), 0 warning(s)`.
- `ansible-playbook servyy.yml --syntax-check -i testing`: parses.
- Deploy `./servyy.sh --limit codey.lehel.xyz --tags "user.repo,user.opencode"` →
  push task reported `created`; item `opencode - server password` present in
  `pass.lehel.xyz`.

### Known Issues

- The push only runs from `codey.lehel.xyz`; a host that runs opencode but is deployed
  without codey in the limit will not refresh the item.
- `bw` must be logged in / loginable via the API key on the controller; a missing
  `~/.ssh/vw.key` silently skips the whole push (`vw_master_password` gate).

## Alternatives Considered

### Also push it from `opencode_authgate.yml` with the API key
Pros: one play, both HTTP credentials together. Cons: that play is gated on
`opencode-authgate` in `services` and is about the ForwardAuth key; the server password
belongs with the OpenCode service role that renders it into `opencode.env`.
**Rejected.**

### Host-suffixed item name (`opencode - server password (codey)`)
Pros: matches `opencode api key (<host>)` naming. Cons: implies per-host values, inviting
someone to "fix" one host's item and desync them. The secret is global.
**Rejected.**

### Manual creation in the Vaultwarden UI
Pros: zero code. Cons: undocumented, not reproducible, and invisible to the next person who
rotates the secret in `secrets.yml` — exactly the drift this repo's Vaultwarden mirroring
exists to prevent.
**Rejected.**
