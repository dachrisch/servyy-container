# LeagueSphere stage DB access via DBeaver — Design

**Date:** 2026-08-07
**Status:** Approved (brainstorm) — pending spec review → implementation plan
**Related:** `docs/leaguesphere-environments.md`, CLAUDE.md § "Off-host Password Backup (Vaultwarden)"

## Problem

An operator needs ad-hoc DBeaver (GUI) access to LeagueSphere's **stage** database — a nightly
clone of live production data (`ls_db_sync`) — from a workstation.

The initial idea (surfaced via an external AI troubleshooting chat, before this design) was to
expose the DB publicly through Traefik at a dedicated hostname. That was rejected during
brainstorming:

- MySQL's wire protocol can't be SNI-multiplexed onto the shared `:443` entrypoint the way this
  repo's HTTP(S) services are (the server speaks first, in cleartext, before any TLS ClientHello)
  — it would require a brand-new dedicated TCP entrypoint and a brand-new hole in the Hetzner
  firewall, both outside this repo's automation.
- It inverts security decisions already made deliberately elsewhere in this same infra: prod's
  `leaguesphere.db` is intentionally on an internal-only network with **no published ports**
  (2026-07-08 cutover), and the SSH chroot jail (`geerlingguy.ssh-chroot-jail`) hardcodes
  `AllowTcpForwarding no` for the LeagueSphere deploy account specifically to prevent this class
  of tunnel.

Two SSH-tunnel variants were also considered and rejected as the final shape:

- **The jailed `leaguesphere` deploy account** — its group inherits `AllowTcpForwarding no` from
  the chroot jail role's `Match group` block; this is a server-side veto that no per-key
  `authorized_keys` option (e.g. `permitopen`) can override. Confirmed by reading the installed
  role defaults directly.
- **The general admin (`cda`) account with a saved tunnel** — works today with zero config
  changes (it's excluded from the jail group), but a key with cda's full reach can forward to
  *any* host-reachable destination, including prod, and the container's internal Docker IP drifts
  across recreations (redeploys, `ls_db_sync`), breaking the saved connection.

## Goal

DBeaver connects to stage via a saved SSH-tunnel profile that is:

1. **Not publicly exposed** — no new firewall port, no public DNS routing.
2. **Stable** — survives stage container recreation without reconfiguration.
3. **Confined to stage by SSH itself**, not by convention — a compromised or misused tunnel key
   must be unable to reach prod or anything else on the host.

**Non-goals:** DBeaver access to the *prod* DB (stage exists precisely so this isn't needed);
building general-purpose remote access infrastructure (Tailscale/WireGuard) — heavier than this
single need justifies; revisit only if broader remote-access requirements emerge later.

## Design

### 1. Stage DB: stable loopback endpoint (`leaguesphere` app repo)

`deployed/docker-compose.staging.yaml`, `mysql` service:

```yaml
ports:
  - "127.0.0.1:33062:3306"
```

Purely additive — the container's existing internal `backend`-network reachability is unchanged.
Loopback-only binding means this port is unreachable from the network or internet under any
circumstance, only from processes running on the host itself. `127.0.0.1` never changes, which
permanently fixes the IP-drift problem (no more `docker inspect` before every reconnect).

Port `33062` is arbitrary — chosen to be visibly distinct from the standard `3306`, not for
obscurity (the security boundary is §2, not the port number).

### 2. Dedicated, isolated SSH account for the tunnel (this repo)

New Linux account `dbeaver_stage` on `lehel.xyz`:

- No `sudo`, no `docker` group, no `leaguesphere`/jail group membership — a standalone account
  with nothing but its own primary group.
- Login shell `/usr/sbin/nologin` (defense in depth alongside the key restriction below).
- Its own keypair, generated the same way the existing deploy key is
  (`ansible.builtin.openssh_keypair`, `delegate_to: localhost`, `force: no`) — private key never
  committed to git, stays on the operator's machine, matching the existing
  `ls_ssh_key_{{ inventory_hostname_short }}` convention.
- `authorized_keys` entry:
  ```
  command="/bin/false",no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="127.0.0.1:33062" <pubkey>
  ```

Why this is a real restriction and not convention: this account is **not** in the jail group, so
the sshd default `AllowTcpForwarding yes` applies to it. `permitopen` is a strict allowlist —
this key can open exactly the one listed destination and nothing else; every other
`direct-tcpip` request is refused by sshd before it ever reaches the network. `command="/bin/false"`
independently forecloses shell/exec use of the account, even though port-forwarding requests
(a separate SSH channel type) are unaffected by it.

New role `ls_dbeaver_access` (deliberately separate from `ls_access` — same shape, but explicitly
*not* jailed), added to `leaguesphere.yml` under tag `ls.dbeaver`.

### 3. Nightly prod → stage sync

New systemd timer, 02:00 UTC, invoking the existing, already-tested `ls_db_sync` Ansible role:

```
ansible-playbook servyy.yml --tags ls.db.sync --limit lehel.xyz
```

Same pattern as the existing `mariadb-backup-ls` / `restic-backup-ls-db` timers. Not an Ofelia
job: the sync is a cross-container operation (`docker exec` dump on prod → `docker cp` → `docker
exec` import on stage, run from the host) — outside what Ofelia's single-container `job-exec`
model fits. Reusing `ls_db_sync` avoids re-implementing that choreography and avoids granting a
new scheduled job Docker-socket access.

### 4. Off-host key backup (Vaultwarden)

Generalize the existing restic → Vaultwarden mechanism (`restic/tasks/{bw_unlock,
vaultwarden_push}.yml` — `bw` CLI, idempotent "create missing items only", Bitwarden Login-type
items) into a shared `vaultwarden` role parameterized by an item list, used by both restic
(behavior unchanged) and this new flow.

Two items pushed (idempotent — already-present items are left alone, which is how "add the
leaguesphere key too, if not already there" is satisfied without a special-case check):

- `leaguesphere deploy key (lehel)` — the existing `ls_ssh_key_lehel` private key.
- `dbeaver stage tunnel key (lehel)` — the new `dbeaver_stage` private key.

`leaguesphere.yml` gains its own `vw_master_password` `vars_prompt` ("press enter to skip"),
mirroring `restic.yml`'s existing UX — declining it is harmless on runs where nothing new needs
pushing.

### 5. DBeaver client configuration

| Tab | Field | Value |
|---|---|---|
| SSH | Host | `lehel.xyz` |
| SSH | User | `dbeaver_stage` |
| SSH | Auth | the new dedicated private key |
| Main | Host | `127.0.0.1` |
| Main | Port | `33062` |
| Main | Database / User | `leaguesphere_stage` (existing credentials — no new DB grants) |

## Tunnel mechanics (for reference)

DBeaver opens an SSH session as `dbeaver_stage`, then requests a `direct-tcpip` channel to
`127.0.0.1:33062`. `sshd` on the host checks the account's `authorized_keys` restrictions,
confirms the target matches the sole `permitopen` entry, and opens a plain TCP connection from
the host's own network namespace to that loopback address — succeeding because the compose
`ports:` mapping in §1 is what's actually listening there. Traffic is relayed back through the
SSH channel to a local port DBeaver binds on the operator's machine; the MariaDB driver connects
to that local port exactly as if it were talking to a local database.

## Testing

- **`servyy-test.lxd` first**, per this repo's standing test-before-prod policy:
  - Deploy `ls_dbeaver_access`; verify the account can open a tunnel to `127.0.0.1:33062` and
    that attempts to forward elsewhere, or to obtain a shell, are refused by sshd.
  - Verify `AllowTcpForwarding` behavior for the jailed and admin accounts is unaffected.
  - Verify the nightly timer successfully triggers `ls_db_sync`.
- Deploy to `lehel.xyz` only after test passes **and** explicit user approval, per repo policy.

## Risks & decisions

- **Cross-repo ordering:** the compose port change lives in the separate `leaguesphere` app repo;
  the SSH-side restriction lives here. Neither half creates an unsafe state on its own — if the
  SSH side lands first, the key just points at a closed loopback port until the compose side
  deploys, and vice versa — but both are needed for the connection to actually work.
- **Vaultwarden dependency:** requires the `bw` CLI and master password on the Ansible controller,
  the same operational dependency the existing restic push already carries.
- **Port `33062` is not itself a security control** — it's only for clarity/avoiding confusion
  with a "real" exposed MySQL port. The actual boundary is the loopback bind (§1) plus the SSH
  `permitopen` restriction (§2).

## Success criteria

- DBeaver connects via the new dedicated account, before and after a stage container recreation,
  with no change to the DBeaver Main-tab host/port.
- The `dbeaver_stage` key is refused by sshd for any destination other than `127.0.0.1:33062` and
  for any shell/exec attempt.
- The nightly timer keeps stage's data fresh unattended.
- Both the LeagueSphere deploy key and the new DBeaver tunnel key are present in Vaultwarden.
