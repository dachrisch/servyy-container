# OpenCode → servy.lehel.xyz SSH Resolution Fix

**Date:** 2026-09-16
**Author:** Claude (via user dachrisch)
**Type:** Bug Fix
**Status:** ✅ Deployed to Production

## Summary

Discovered and fixed a two-part bug that made `ssh servy.lehel.xyz` from inside the
OpenCode container on `codey.lehel.xyz` silently connect to the wrong host. Both
issues were leftovers from the DNS restructuring that moved OpenCode from running
on `servy.lehel.xyz` (aka `lehel.xyz`) to its own dedicated `codey.lehel.xyz` server
(see `bed071a`, 2026-09-11) — the code was never fully updated for the new topology.

## Problem

While investigating whether opencode could reach both servy.lehel.xyz and
codey.lehel.xyz over SSH, `docker ps` output from both hostnames turned out
identical (codey's 7-container list), even though direct SSH from the workstation
showed the two servers have completely different container sets (servy: 48
containers, codey: 7). `ssh servy.lehel.xyz` from inside opencode was silently
reaching codey instead of the real servy server.

### Root cause 1 — stale SSH config override

`opencode/scripts/provision-dev.sh` (run on every container boot) wrote:

```
Host servy.lehel.xyz lehel.xyz
  HostName host.docker.internal
  User cda
  IdentityFile ~/.ssh/id_servy
```

`HostName host.docker.internal` resolves to the Docker host the *container itself*
runs on. When opencode ran on `servy.lehel.xyz`, that correctly meant "the box I'm
on." After the move to `codey.lehel.xyz`, it silently meant "codey" instead —
looping `servy.lehel.xyz` SSH traffic back to codey with no error.

### Root cause 2 — stale IP-restricted authorized_keys

Once root cause 1 was fixed, opencode began genuinely attempting to reach the real
`servy.lehel.xyz` — and was rejected. `servy.lehel.xyz`'s `authorized_keys` for
`cda` scoped opencode's key to:

```
from="172.16.0.0/12,127.0.0.1"
```

Correct when opencode ran on servy itself (same-host connections always show a
docker-range source IP), but a genuine cross-server connection from codey arrives
from codey's real public IP/IPv6 address, which doesn't match that range.

## Solution

### Fix 1 — provision-dev.sh (PR #128)

Dropped the `HostName host.docker.internal` override and scoped the `Host` block
to just the two real hosts `id_servy` is authorized on:

```
Host servy.lehel.xyz codey.lehel.xyz
  User cda
  IdentityFile ~/.ssh/id_servy
  StrictHostKeyChecking accept-new
```

Both hostnames now resolve via real DNS.

### Fix 2 — docker_extras.yml (PR #129)

Resolve `codey.lehel.xyz`'s current A/AAAA records via Ansible's `dig` lookup at
deploy time (no hardcoded IP — user explicitly required this) and append them to
the key's `from=` allowlist alongside the existing docker-network scope:

```yaml
- name: Resolve codey.lehel.xyz addresses for OpenCode SSH key restriction
  ansible.builtin.set_fact:
    opencode_codey_ipv4: "{{ lookup('dig', 'codey.lehel.xyz', 'qtype=A') }}"
    opencode_codey_ipv6: "{{ lookup('dig', 'codey.lehel.xyz', 'qtype=AAAA') }}"

- name: Authorize OpenCode container SSH key (scoped to local docker networks + codey.lehel.xyz)
  ansible.posix.authorized_key:
    key_options: >-
      from="172.16.0.0/12,127.0.0.1{{
      ',' + opencode_codey_ipv4 + '/32' if opencode_codey_ipv4 not in ['', 'NXDOMAIN'] else ''
      }}{{
      ',' + opencode_codey_ipv6 + '/128' if opencode_codey_ipv6 not in ['', 'NXDOMAIN'] else ''
      }}"
```

Reverse DNS (PTR) doesn't exist for either of codey's addresses, ruling out an
OpenSSH hostname-pattern `from=` match — hence the dynamic IP lookup instead.

## Files Changed

- `opencode/scripts/provision-dev.sh` — PR #128
- `ansible/plays/roles/user/tasks/docker_extras.yml` — PR #129

## Testing

Both fixes tested on `servyy-test.lxd` before production, per repo policy.

**Fix 1:**
```bash
cd ansible && ./servyy-test.sh --tags "user.docker.repo,user.docker.opencode" --limit servyy-test.lxd
```
Verified rendered `~/.ssh/config` inside `opencode.web` had no `HostName` override;
`getent hosts servy.lehel.xyz codey.lehel.xyz` inside the container returned two
distinct real DNS addresses.

**Fix 2:**
```bash
cd ansible && ./servyy-test.sh --tags "user.docker.repo,user.ssh.opencode" --limit servyy-test.lxd
```
Verified rendered `authorized_keys` entry:
```
from="172.16.0.0/12,127.0.0.1,217.217.227.124/32,2a01:8740:1:fa3::54ad/128" ssh-ed25519 ... opencode-container-servy
```

Test-environment SSH auth itself correctly failed with `Permission denied` in both
cases (test's `id_servy` key isn't authorized on the real production servers —
correct isolation, not a bug).

## Production Deployment

**Date:** 2026-09-16
**Targets:** `codey.lehel.xyz` (fix 1), `servy.lehel.xyz` (fix 2)

```bash
cd ansible && ./servyy.sh --tags "user.docker.repo,user.docker.opencode" --limit codey.lehel.xyz
cd ansible && ./servyy.sh --tags "user.ssh.opencode" --limit servy.lehel.xyz
```

**Results:**
```
codey.lehel.xyz   : ok=55  changed=13  unreachable=0  failed=1  (unrelated Vaultwarden handler, see below)
servy.lehel.xyz   : ok=18  changed=1   unreachable=0  failed=0
```

End-to-end verification from the real production opencode container:
```bash
ssh codey.lehel.xyz "docker exec opencode.web ssh servy.lehel.xyz docker ps --format '{{.Names}}'"
```
Returned servy's real container list (`leaguesphere.*`, `dontforget.web`,
`finance.firefly`, ...) — confirming opencode now genuinely reaches servy, not a
self-loop back to codey.

**PRs:** [#128](https://github.com/dachrisch/servyy-container/pull/128),
[#129](https://github.com/dachrisch/servyy-container/pull/129) — both admin-merged
past a blocked required `Molecule Test` check (see below).

## Known Issues (pre-existing, unrelated to this fix)

- **CI blocked by broken upstream role:** `ansible/requirements.yml` pins
  `sebthebert.ubuntu_pro` unversioned (tracks its `main` branch). That branch
  currently has malformed YAML in `tasks/main.yml:16` (`when: state == 'update'`
  missing its list-item indent), which fails every `Ansible Syntax Check` job and,
  transitively, the required `Molecule Test` check (`needs: [..., syntax-check]`
  in `.github/workflows/ci.yml`). This blocks merging *any* PR until either
  upstream fixes it or this repo pins the role to a known-good ref. Both PRs in
  this session were merged past it via `gh pr merge --admin` with explicit user
  approval each time.
- **Vaultwarden push handler failure:** the `codey.lehel.xyz` deploy for fix 1 had
  `failed=1` on `opencode : Build map of existing items for our push list` —
  `bw_items_raw.stdout` wasn't valid JSON, most likely because the interactive
  Vaultwarden master-password prompt was skipped during this non-interactive
  background deployment run. Did not block the opencode fix itself. Not
  investigated further this session.

## Future Enhancements

- Pin `sebthebert.ubuntu_pro` to a known-good commit/tag in
  `ansible/requirements.yml` to stop tracking its `main` branch.
- Investigate the Vaultwarden push handler failure and confirm it isn't silently
  failing on every non-interactive deploy.
