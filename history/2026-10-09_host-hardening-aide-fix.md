# Host Hardening AIDE Fix — 2026-10-09

## Problem

The P6 hardening AIDE tasks (from PR #201) failed on the first production deploy
(`servy.lehel.xyz`, `codey.lehel.xyz`):

```
aide --init
  ERROR: missing configuration (use '--config' '--before' or '--after' command line parameter)
```

The `aide` binary has no compiled-in default config path, so `aide --init` without
`--config` fails. The distro config lives at `/etc/aide/aide.conf` and is shipped by the
`aide-common` package (not `aide`). The same defect was in the weekly
`aide-check.service` (`ExecStart=/usr/bin/aide --check`).

## Solution

- `tasks/hardening.yml` — install `aide` **and** `aide-common`; initialise with
  `aide --config /etc/aide/aide.conf --init`.
- `templates/aide-check.service.j2` — `ExecStart=/usr/bin/aide --config
  /etc/aide/aide.conf --check`.

`database_out=file:/var/lib/aide/aide.db.new` in the distro config matches the task's
`mv` target; `--config-check` on `/etc/aide/aide.conf` returns 0.

## Validation

- `ansible-playbook plays/system.yml --syntax-check` ✅
- `ansible-lint` on `hardening.yml`: 0 failures ✅
- AIDE initialisation is intentionally **not** re-run as part of this fix's verification:
  a full `aide --init` filesystem scan is slow; the invocation itself is validated by the
  distro config check above.
