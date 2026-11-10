# 2026-11-10 — servy's SSH jails were blind to OpenSSH 10's `sshd-session`

Follow-up to `history/2026-11-10_fail2ban-web-tier-chain-fix.md` (same lockout, different
defect). The web-tier jail never blocked anything because it hooked `INPUT`; the two *SSH*
jails have a separate problem — on servy they match almost nothing.

## Why we looked

The operator lockout on 2026-11-10 was recorded on both hosts, but the jails that fired
differed, and one of them had never fired at all:

| Host | OpenSSH | fail2ban | Jails that banned `45.155.141.31` |
|---|---|---|---|
| servy | 10.2p1 | 1.1.0 | `sshd`, `loki-blocklist` |
| codey | 9.6p1 | 1.0.2 | `sshd`, `sshd-invalid-user` |

`sshd-invalid-user` had **0 total bans in servy's entire retained `fail2ban.log`**, while
codey's showed 143 in the current period and 6346 across its logs. A jail that never bans
anything is the same silent failure the layer below fixes for the web tier.

## Finding 1 — `_COMM=sshd` drops ~95% of the unit's events

`/etc/fail2ban/jail.d/defaults-debian.conf` ships the backend *and* the journal match, and
it differs between our hosts (codey sets `backend` on `[DEFAULT]`; servy sets both only on
`[sshd]`). On servy it pins:

```
[sshd]
backend = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd
```

OpenSSH 10 splits the listener (`sshd`) from the per-connection process (`sshd-session`), and
connection/authentication events come from the latter. Measured on servy, 400 most recent
`ssh.service` journal entries:

```
379  ('sshd-session', 'sshd-session', 'ssh.service')
 21  ('sshd',         'sshd',         'ssh.service')
```

So `_COMM=sshd` matched 21 of 400. The ban we got on 2026-11-10 was a **fluke**: the only
line the jail could see from the scanner's burst was the listener's rate-limit notice —

```
08:42:27 servy sshd-session[842716]: Invalid user  from 45.155.141.31 port 3334     <- invisible
08:42:28 servy sshd[1237]: srclimit_penalise: ipv4: new 45.155.141.31/32 ...        <- the one that matched
```

A real brute-force that does not trip `srclimit` would have been invisible to the jail.
codey is unaffected only because OpenSSH 9.6 still logs everything as `sshd`.

## Finding 2 — the custom filter hard-coded `sshd[`

fail2ban's systemd backend renders each entry as `_HOSTNAME SYSLOG_IDENTIFIER[pid]: MESSAGE`
(`filtersystemd.formatJournalEntry`), so the line genuinely contains `sshd-session[842716]:`.
`filter.d/sshd-custom.conf.j2` matched `^.* sshd\[\d+\]: Invalid user …` — the literal `sshd[`
cannot match `sshd-session[`, so on servy the jail had nothing to match even where the
journal match did deliver the line. `Connection closed by invalid user <HOST>` (what a
blank-username probe leaves behind) was not matched on any host.

## Changes

| File | Change |
|---|---|
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | `[DEFAULT] backend = systemd` declared instead of inherited; both SSH jails get `journalmatch = _SYSTEMD_UNIT=ssh.service`; the dead `logpath = /var/log/auth.log` lines are gone |
| `ansible/plays/roles/system/templates/fail2ban/filter.d/sshd-custom.conf.j2` | all four failregexes match `sshd(?:-session)?\[\d+\]:`; `Connection closed by invalid user` added |
| `ansible/plays/roles/system/molecule/with-docker/verify.yml` | asserts `backend = systemd`, no `auth.log` logpath, no `_COMM=`, `journalmatch` count == 2, and that all four failregexes carry the ident alternation |
| `CLAUDE.md` | "No file is currently monitored" is expected; how to check the journal match |

`logpath` was not merely redundant: codey has **no `/var/log/auth.log` at all**, so the old
line named a file that never existed, and `fail2ban-client get sshd logpath` answered
"No file is currently monitored" on both hosts. Removing it makes the config say what it
does. `[loki-blocklist]` keeps `backend = polling` — it reads the file its script writes.

## Verification

- Templates rendered with the same inputs the molecule assertions use (jinja2 3.1.6):
  **17/17 checks pass** — layer-1 assertions (web ports, `chain = DOCKER-USER`,
  `chain = INPUT` without Docker) still hold, the new config assertions hold, and
  `[loki-blocklist]` still renders `backend = polling`.
- The new failregexes were run against **real captured lines** from both hosts, rendered the
  way `filtersystemd.formatJournalEntry` produces them:
  - `servy sshd-session[842716]: Invalid user  from 45.155.141.31 port 3334` → matches (was invisible)
  - `servy sshd-session[842716]: Connection closed by invalid user  45.155.141.31 …` → matches
  - `codey sshd[1759625]: Invalid user a3user from 212.114.180.131 …` → still matches
  - regression proof: the old `sshd\[` patterns do **not** match the servy line.
- `yamllint`, `ansible-lint` and `ansible-playbook --syntax-check` pass locally. The same
  assertions from `molecule/with-docker/verify.yml` were run through `ansible-playbook`
  against the real templates (identical lookups/expressions) and pass — molecule itself
  cannot run in the dev container (no Docker socket), so the scenario runs in CI.

## To deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban --check --diff
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban
./servyy.sh --limit codey.lehel.xyz --tags system.fail2ban
```

Then confirm the jails see events on both hosts — `sshd-invalid-user` must stop being a
zero on servy:

```bash
ssh servy.lehel.xyz "sudo journalctl -u fail2ban -n 30 --no-pager | grep -i 'sshd-invalid-user'"
ssh servy.lehel.xyz "sudo fail2ban-client status sshd-invalid-user"
ssh codey.lehel.xyz "sudo fail2ban-client status sshd"
```

## Notes / follow-ups

- **IPv6 is still uncovered** by both SSH jails (carried over from the layer below): the
  `iptables-multiport` action writes v4 rules only.
- **The CGNAT collision itself is unfixed by design.** `45.155.141.0/24` is a shared
  subscriber pool, so a neighbour's scanner gets the operator's address banned. That is a
  routing/identity problem, not a fail2ban one: dedicated public IPv4, or SSH over
  WireGuard/Tailscale.
- **Version drift is the underlying trap.** Two hosts, two fail2ban versions, two OpenSSH
  versions, and a distro file whose contents differ between them — anything the template
  leaves to the package will diverge again.
