# Host Hardening sshd Drop-in Fix — 2026-10-09

## Problem

The P6 hardening SSH drop-in (`ansible/plays/roles/system/templates/sshd-hardening.conf.j2`)
rendered YAML boolean values verbatim. In `ansible/plays/vars/default.yml` the values
`TCPKeepAlive: no` and `AllowAgentForwarding: no` are parsed by YAML as the boolean
`False`, so the template emitted:

```
TCPKeepAlive False
AllowAgentForwarding False
```

The deploy task validates the rendered file with `sshd -t -f %s`, which rejected it with
`unsupported option "False"`. The first real deploy (servyy-test.lxd, PR #201) failed at
`Deploy SSH hardening drop-in` — no broken `sshd_config` was written (the validate step
correctly aborted before install), so there was no lockout risk.

Molecule did not catch this: only the `core` scenario runs hardening, and it sets
`ssh: {}` (no sshd in the container) so the SSH drop-in is skipped.

## Solution

- `templates/sshd-hardening.conf.j2` — render booleans as sshd `yes`/`no`, leaving all
  non-boolean values (e.g. `LogLevel VERBOSE`) untouched so their case is preserved.
- `molecule/core/converge.yml` + `verify.yml` — render the template from a YAML-boolean
  sample (no sshd required) and assert it emits `TCPKeepAlive no` / `AllowAgentForwarding
  no` and contains no `True`/`False` tokens.

## Validation

- `ansible-playbook plays/system.yml --syntax-check` ✅
- yamllint / ansible-lint ✅
- Molecule `system/core` exercises the template render + assertions.
- Real deploy re-run on `servyy-test.lxd`, then production (`servy.lehel.xyz`,
  `codey.lehel.xyz`) with `--tags system.hardening,system.security_audit`.
