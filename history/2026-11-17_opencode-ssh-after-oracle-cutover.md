# ADR: Make OpenCode's container→host SSH survive a machine move

**Date:** 2026-11-17
**Status:** Accepted — deployed to `codey.lehel.xyz` and `servy.lehel.xyz`
**Relates to:** ADR `2026-11-17_oracle-codey-replication` (the move that exposed this),
ADR `2026-09-16_opencode-servy-ssh-resolution-fix` (whose `dig`-based allow-list this
replaces)

## Context

The `check-server-status` skill asks for `ssh servy.lehel.xyz` and `ssh codey.lehel.xyz`
from inside the opencode container. After the codey role moved onto the Oracle A1 both
connections were dead, so "check the servers" had to be done from the workstation
instead — the one place the skill is not meant to run. Two independent cutover
leftovers, both of which had been *correct* for the old topology:

### Root cause 1 — the container's own host key was a repo constant

`roles/opencode/tasks/main.yml` wrote a hardcoded `codey.lehel.xyz ssh-ed25519 AAAA…`
line into the container's mounted `known_hosts`. The constant was the retired VPS's
host key, so the container got:

```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
Offending ED25519 key in /root/.ssh/known_hosts:2
The fingerprint for the ED25519 key sent by the remote host is SHA256:cL7w3J…
```

`codey.lehel.xyz` is the *only* name the status skill uses for that host, so this alone
removed half the skill.

### Root cause 2 — the `from=` allow-list was frozen at the last deploy

`roles/user/tasks/docker_extras.yml` scoped the container's `id_servy` public key with
`from=` built from `lookup('dig', 'codey.lehel.xyz')` **on the deploying host at deploy
time**. That is a snapshot, not a fact: after the cutover the live host was
`138.2.180.191`, while `servy` still held

```
from="172.16.0.0/12,127.0.0.1,217.217.227.124/32,2a01:8740:1:fa3::54ad/128"
```

i.e. exactly the retired VPS and nothing live. `servy`'s sshd logged the real attempt:

```
Connection from 138.2.180.191 port 60078 on 49.13.6.173 port 22
Failed publickey for cda from 138.2.180.191 … ED25519 SHA256:IHPuSL…
```

Because the deploy that *would* have refreshed the list never ran after the DNS change,
the restriction silently inverted: it admitted the machine that was leaving and rejected
the one that arrived. `codey`'s own `authorized_keys` carried the same stale list, which
is why the container could only reach its own host through the docker gateway
(`172.16.0.0/12`) and not by name.

## Decision

**Own host key: derive it from the host, not the repo.** Slurp
`/etc/ssh/ssh_host_ed25519_key.pub` during the deploy and write
`{{ inventory_hostname }} <type> <key>`. A machine move can no longer leave the pin
pointing at the previous machine, and the same task repairs an existing stale line
because it matches `regexp: '^{{ inventory_hostname | regex_escape }} '` — with a bare
`line` lineinfile would *append* a second entry, and OpenSSH reports "changed" if any
entry for that host+type disagrees, so the stale key would keep winning.

`servy.lehel.xyz` deliberately stays a repo-pinned constant: it is a different machine's
key, there is nothing local to read, and a `ssh-keyscan` would convert the pin into
trust-on-first-use. A servy rebuild therefore remains an explicit repo change.

**Cross-host allow-list: read inventory, not DNS.** Build `from=` from
`hostvars['codey.lehel.xyz'].ansible_host` and `.ipv6_address`. Those are the same values
Ansible itself uses to reach the host, so an address change is a reviewed inventory edit
that redeploys in the same run — and a stale inventory address breaks the deploy loudly
instead of silently widening (or inverting) the key scope. Only IP literals are admitted,
because `servyy-test.lxd` uses its name as `ansible_host` and a hostname is not a valid
`from=` pattern: sshd would refuse *every* connection rather than ignore the entry.

## Consequences

### Positive

- ✅ `ssh servy.lehel.xyz` and `ssh codey.lehel.xyz` work from inside the container again;
  the `check-server-status` skill runs where it is documented to run.
- ✅ Both remaining stale-state classes on this path are gone: a host-key change and an
  address change are now *derived at deploy time* rather than remembered in the repo.
- ✅ No more keyscan, no TOFU for the fleet's own hosts, and the pin for a foreign host
  (servy) is still an explicit, reviewable constant.
- ✅ Cheaper than the alternative: one `slurp` + one templated line, no new role, no
  network dependency at deploy time.

### Negative / Tradeoffs

- ⚠️ The allow-list now trusts the inventory's `ansible_host` to *be* the egress address.
  True on OCI (IGW NATs to the VNIC's public IP, and the GUA is assigned to the VNIC), but
  a host behind NAT or a bastion would need a dedicated variable instead.
- ⚠️ The `from=` list no longer follows a DNS change made outside the repo. That is the
  point, but it means a manual DNS edit without an inventory edit leaves the old address
  allowed until the next deploy.
- ⚠️ The own-host entry is keyed on `inventory_hostname`, so a rename would drop the old
  entry only via the new `regexp`. Both codey names still resolve to the same box, so
  `code.lehel.xyz` is not covered by the own-host line (nothing in the container uses it;
  programmatic clients use the HTTP API).

### Implementation Details

**Files modified:**
- `ansible/plays/roles/opencode/tasks/main.yml` (MODIFY) — `codey.lehel.xyz` constant →
  `slurp` + `lineinfile` with `regexp`; new tag `opencode.known_hosts`; comment on why
  servy's constant stays.
- `ansible/plays/roles/user/tasks/docker_extras.yml` (MODIFY) — drop the `dig` `set_fact`
  and the `NXDOMAIN` string handling; `from=` from inventory hostvars, IP-literal filtered.

**Commits:**
- `92c0550` fix(opencode): repair the container's SSH to both hosts after the Oracle cutover
- this ADR

**Testing & Verification:**

Applied with the narrowest tags so no unrelated drift landed:

```bash
cd ansible
ansible-playbook plays/user.yml --limit codey.lehel.xyz -i production --tags opencode.known_hosts
ansible-playbook plays/user.yml --limit 'codey.lehel.xyz,servy.lehel.xyz' -i production --tags user.ssh.opencode
```

- ✅ First runs: `changed=1` on each host; immediate re-runs: `changed=0` (idempotent).
- ✅ `known_hosts` line for `codey.lehel.xyz` now verifies as `SHA256:cL7w3J…`, matching
  `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the host itself — the old
  `SHA256:qyt2Vj…` line is gone (replaced, not appended).
- ✅ Both hosts' `authorized_keys`:
  `from="172.16.0.0/12,127.0.0.1,138.2.180.191/32,2603:c020:802e:5f01:0:876f:f045:3504/128"`.
- ✅ From inside `opencode.web` on codey: `servy.lehel.xyz OK`, `codey.lehel.xyz OK`.
- ✅ `check-status.sh codey.lehel.xyz` and `check-status.sh servy.lehel.xyz` both return
  full output (disk 22 %, 8/8 containers Up, 3 fail2ban jails, monit all OK on codey;
  servy timers all firing on schedule, `traefik.lehel.xyz` → 401, `monitor.lehel.xyz` → 302).
- ✅ Egress addresses confirmed independently of the inventory:
  `curl -4/https://ifconfig.co` → `138.2.180.191`, `curl -6` → `2603:c020:…:3504`.

**Key Learnings:**

1. **A digest of "current state" decays.** The 2026-09-16 fix chose a deploy-time `dig`
   precisely to avoid a hardcoded IP (a stated requirement then). But a deploy happens
   *before* the thing it describes changes — during a cutover the lookup resolves the old
   address by definition, and nothing re-runs it afterwards. Deriving from the inventory
   is the same "no hardcoded IP" property with a deploy-time refresh.
2. **`lineinfile` + `line` is append-only; `regexp` is the repair.** The stale known_hosts
   entry would have survived a naive fix and continued to fail, because a duplicate entry
   with a disagreeing key is still a hard error.
3. **A scoped allow-list that nobody redeploys fails closed to the *wrong* peer.** The
   error surface ("Permission denied (publickey)") looks like a key problem, not a
   stale-config problem, which is why it was only found by reading servy's sshd journal.

### Known Issues & Limitations

- `LOCAL_HOSTNAME` in `opencode/.env` still reads `oracle-codey.lehel.xyz`; a full user
  play would render it as `codey.lehel.xyz` (unrelated drift observed in `--check`, not
  applied here).
- **Cutover residue, measured while closing this out** (not SSH health, so left outside
  the fix itself):
  - `h.code.lehel.xyz` needs no DNS cleanup — there is no record, and it does not resolve
    at all, because `*.lehel.xyz` matches one label only and this name has two. The
    devhub container and volume are gone from both hosts; the only remain was a stale
    8 KiB `~/servyy-container/devhub/docker-compose.yml` on the Oracle box, which was
    removed (the service is `devhub: false`, and the file is regenerated from the repo if
    ever re-enabled).
  - The retired alphavps box (`217.217.227.124`) is still up (SSH :22, no containers)
    holding the four volumes that were kept by the teardown: `codey_dev_checkouts` 6.6 G
    (rebuildable), `opencode_opencode_root` 3.5 G (the pre-cutover sessions DB),
    `devhub_sqlite_data` 141 M, `traefik_traefik-certificates` 132 K. It no longer *writes*
    backups — only `restic-forget`/`restic-check` units remain, and `restic-forget` has
    been failing since 2026-11-17 05:01 ("Some repositories failed retention policy") — so
    whatever is not already in the Storage Box repository exists only on that disk.
    Destroying it therefore needs an explicit decision plus a deliberate snapshot of
    `devhub_sqlite_data` and the old opencode DB first.

## Related Decisions

- ADR `2026-11-17_oracle-codey-replication` — the move that invalidated both constants.
- ADR `2026-09-16_opencode-servy-ssh-resolution-fix` — ADR that introduced the `dig`
  allow-list; superseded by this one for the address source.
- `check-server-status` skill — the consumer whose documented procedure this restores.

## Alternatives Considered

**Keep the hardcoded codey host key and just paste the new one.** Simplest one-line diff,
and it is what a "just make it work" fix looks like. Rejected: this is the second time a
repo constant had to be hand-updated for a machine move, and the failure mode is a
container that cannot reach its own host — silently, until someone reads the log.

**`ssh-keyscan` the host during the deploy (for both entries).** No constants at all.
Rejected: it converts host-key verification into trust-on-first-use, exactly when the
deploy is the only thing that could notice an interception. Reading the local key file
keeps the guarantee for the host we control.

**Union the `dig` result with the inventory values.** Never breaks on either source
being stale. Rejected: it keeps an allow-list entry for an address that may no longer be
ours — after the retired VPS's IP is released back to the provider, someone else's
machine would match `217.217.227.124/32` with that key. Failing closed to the inventory
is the safer direction.

**A dedicated `opencode_peer_addresses` inventory variable.** Explicit and self-describing.
Deferred, not rejected: `ansible_host` + `ipv6_address` are already exactly those values
for this host, and a second variable is another thing to forget. Revisit if a host ever
reaches out from something other than its inventory address.
