# 2026-11-11 — SSH jails ban for 1 hour, repeat offenders escalate

Fourth layer of the 2026-11-10 fail2ban work (chain → journal scope → address family → ban
duration). The previous three fixed bans that never landed. This one fixes what a ban *costs*
when it does land.

## Why

The SSH jails banned for **24 h**. That is the wrong duration for an interactive service: one
mistyped password on the operator's own line, or one laptop with a stale key, meant a full day
without SSH to the box you may need to fix. `maxretry 3 / findtime 3600` means a real scanner
is re-banned after three more attempts, so a long ban buys almost nothing against an attacker
and is expensive against ourselves. The web-tier jail (`loki-blocklist`) keeps its 24 h — that
is abuse traffic, not a typo, and it is already scoped to `http,https`.

A flat short ban would be a downgrade against a persistent source, so the short base is paired
with escalation: each successive ban for the same source doubles, capped at a day.

| Jail | Before | After |
|---|---|---|
| `[sshd]` | `bantime = 86400` | `bantime = 3600`, escalating |
| `[sshd-invalid-user]` | `bantime = 86400` | `bantime = 3600`, escalating |
| `[loki-blocklist]` | `bantime = 86400` | unchanged (`= maxtime`, so escalation caps at the same day) |

Resulting curve for a returning source: **1 h → 2 h → 4 h → 8 h → 16 h → 24 h (cap)**.

## Changes

| File | Change |
|---|---|
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | SSH jails at `3600`; `[DEFAULT]` gets `bantime.increment = true`, `bantime.factor = 1`, `bantime.maxtime = 86400` |
| `ansible/plays/roles/system/templates/fail2ban/fail2ban.local.j2` | **new** — `[Definition] dbpurgeage = 604800` (server option, see below) |
| `ansible/plays/roles/system/tasks/fail2ban.yml` | deploys `fail2ban.local` to `/etc/fail2ban/` |
| `ansible/plays/roles/system/molecule/with-docker/verify.yml` | section-scoped assertions: both SSH jails `3600` and no `86400`, `[DEFAULT]` increment/factor/maxtime, `loki-blocklist` still `86400` and no increment, server template carries `dbpurgeage` |

## Three things this change had to be corrected for

### 1. `bantime.factor = 2` is not "double"

The built-in formula is already `ban.Time * 2^bancount`. `factor` multiplies **on top** of
that, so `factor = 2` gives 1 h → 4 h → 8 h → 16 h, skipping the intended 2 h step. Deployed at
`factor = 1`; the doubling comes from the formula. The template comment states this so the
value is not "fixed" back to 2 later.

### 2. `dbpurgeage` in `jail.local` is a silent no-op

Escalation reads the ban history from the database, and that history is purged after
`dbpurgeage` (default 1 day). The curve 1 h + 2 h + 4 h + 8 h + 16 h spans **31 h**, so the
default window would drop the early bans mid-escalation and reset the count.

`dbpurgeage` is a **server** option (`fail2ban.conf` `[Definition]`), not a jail option. A copy
in `jail.local` parses without error and does nothing — measured on the test host:

```
$ sudo fail2ban-client get dbpurgeage
`- 86400seconds        # with dbpurgeage = 604800 sitting in jail.local
```

Hence the new `fail2ban.local.j2`; after deploying it the same command reports `604800seconds`.
The molecule check asserts `dbpurgeage` is **absent** from the jail config and present in the
server config, so it cannot drift back.

### 3. This cannot be proven with `fail2ban-client set … banip`

The obvious proof — ban a documentation address, unban, ban again — shows a flat 3600 every
time. It is the wrong instrument: `unbanip` goes through `actions.removeBannedIP`, which calls
`database.delBan` and deletes the row from **both** `bans` and `bips`, i.e. it erases exactly
the history `bantime.increment` reads. Increment lives on the *failure* path
(`observer.failureFound` / `incrBanTime`), and needs `maxretry > 1` to climb (the retry counter
is clamped to `maxretry`).

## Verification

- **Isolated instance on the test host** (`fail2ban-server -c /tmp/f2bt -s /tmp/f2bt/f2b.sock`,
  base `bantime = 2s`, `maxretry = 2`, `factor = 1`, its own `dbfile`) fed one `Failed password`
  line per second for a documentation address. The database escalates exactly as intended:

  ```
  t=06s ban=(2, 1) bips=(2, 1)
  t=12s ban=(2, 1) bips=(4, 2)
  t=42s ban=(2, 1) bips=(8, 3)
  ...observer: IP 192.0.2.55 is bad: 2 # last ... - incr 2s to 8s
  ...observer: Increase Ban 192.0.2.55 (3 # 8s -> ...)
  ```

  The curve is multiplicative, so 2 s → 4 s → 8 s is the same curve as 1 h → 2 h → 4 h. Scratch
  config, chain `F2BTEST` and socket removed afterwards; production jails untouched.
- **Rendered-config assertions** run locally against the role templates (identical expressions
  to `molecule/with-docker/verify.yml`, which CI runs with `with_fail2ban: false` because the
  daemon needs real logs).
- **Live, after deploy** (servy / codey, both `fail2ban` 1.1.0 / 1.0.2):

  | Check | servy | codey |
  |---|---|---|
  | `get sshd bantime` | 3600 | 3600 |
  | `get sshd-invalid-user bantime` | 3600 | 3600 |
  | `get loki-blocklist bantime` | 86400 | 86400 |
  | `bantime.increment` / `factor` / `maxtime` | True / 1 / 86400 | True / 1 / 86400 |
  | `get dbpurgeage` | 604800 | 604800 |

- **Restart kept the bans.** The previous layer's incident (no bans for ~2 min after a bad
  action set) made this the check that matters: bans restored from the database unchanged —
  servy 9 / 10 / 77, codey 36 / 38 / 0 for `sshd` / `sshd-invalid-user` / `loki-blocklist`,
  with `f2b-sshd` rules (10 + 1 v6, 37 + 1 v6) and the `DOCKER-USER` jump intact. Existing
  24 h bans keep their original expiry; only new bans use the new duration.

## Consequences / known limitations

- ⚠️ A source banned once can retry after an hour, costing three failed attempts per re-ban.
  That is the trade accepted here; escalation is what makes it sustainable.
- ⚠️ Escalation state is in `/var/lib/fail2ban/fail2ban.sqlite3`. If that database is lost or
  the host reimaged, escalation restarts from 1 h (bans still happen, just flat).
- ⚠️ The 24 h cap means a source that returns daily converges to one 24 h ban per day — it is
  not intended to be a permanent blocklist; that is what `loki-blocklist` is for.
- ⚠️ Molecule cannot exercise the daemon (`with_fail2ban: false` in every scenario), so the
  escalation itself is proven by the isolated-instance run above, not by CI.

## Alternatives considered

- **Flat 1 h, no escalation** — simplest, but a persistent scanner just cycles every hour.
  Rejected: costs nothing to escalate.
- **Keep 24 h but add a 1 h `findtime`** — does not address the operator lockout at all.
- **`bantime.factor = 2`** — doubles in addition to the formula's own doubling; would have
  made the first re-ban 4 h. Rejected after measurement.
- **`bantime.multipliers`** — explicit list of steps, but more surface for no gain over the
  default formula.

## To deploy (repeatable)

```bash
cd ansible
ansible-playbook servyy.yml -i testing --limit servyy-test.lxd --tags system.fail2ban \
  -e ansible_host=10.185.182.250   # servyy-test.lxd does not resolve from the dev box
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban --check --diff
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban
./servyy.sh --limit codey.lehel.xyz --tags system.fail2ban
```

Verify: `fail2ban-client get sshd bantime`, `fail2ban-client get dbpurgeage`, and
`fail2ban-client status <jail>` (bans must survive the restart).

## Related decisions

- `history/2026-10-30_fail2ban-web-only-ban.md` — why the web-tier jail bans a full day.
- `history/2026-11-10_fail2ban-web-tier-chain-fix.md` — the chain the web-tier rules land in.
- `history/2026-11-10_fail2ban-openssh10-sshd-session.md` — which journal events the SSH jails see.
- `history/2026-11-11_fail2ban-ipv6-ssh.md` — both address families banned.
