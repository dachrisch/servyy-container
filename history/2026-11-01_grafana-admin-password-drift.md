# ADR: Grafana admin password drift — a controller-local seed generated a second password

**Date:** 2026-11-01
**Status:** Accepted
**Relates to:** [`2026-06-29_restic-seed-guard.md`](2026-06-29_restic-seed-guard.md) (the guard that restic has and this secret did not), [`2026-06-29_restic-vaultwarden-copy.md`](2026-06-29_restic-vaultwarden-copy.md) (the Vaultwarden backup-copy pattern reused here), [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md) (why a monitor-only deploy has to be run from an up-to-date controller checkout)

## Context

Deploys run from the opencode server (`codey.lehel.xyz`) reported the Grafana admin
password as drifting: `monitor/grafana.env` came back `changed` on a deploy that should
have been idempotent, and the password in that file no longer logged in to
`monitor.lehel.xyz` (HTTP 401), while the previously documented password still did (HTTP 200).

`vault_monitor_grafana_admin_password` is not a literal in `secrets.yml` — it is a
controller-local generated seed:

```yaml
vault_monitor_grafana_admin_password: "{{ lookup('password', 'vars/.monitor_grafana_admin_password length=32 chars=ascii_letters,digits') }}"
```

The seed file is gitignored (`ansible/.gitignore`), so it exists **only on the controller
that first rendered it** — in this case the dev workstation (`delly`, seed created
2026-10-09). The opencode server's checkout (`servyy-deploy-master`, inside the
`codey_dev_checkouts` docker volume) had no seed, so the first monitor deploy from there
**generated a brand-new password** and rendered it over the live file.

The evidence is a byte-for-byte content match, not an inference:

| Artifact | sha256[:16] | mtime |
|---|---|---|
| `delly` seed `ansible/plays/vars/.monitor_grafana_admin_password` (source of truth) | `b2b2683d2b5fb940` | 2026-10-09 00:22 |
| `codey` seed generated in `servyy-deploy-master/ansible/plays/vars/` | `9e76b9c37876e95c` | 2026-10-31 21:01 |
| `servy` `/home/cda/servyy-container/monitor/grafana.env` | `9e76b9c37876e95c` | 2026-10-31 21:01:54 |
| running `monitor.grafana` container env | `9e76b9c37876e95c` | started 21:02:08 |

Two facts made this harmless *today* and dangerous *tomorrow*:

1. **Grafana applies `GF_SECURITY_ADMIN_PASSWORD` only when it first creates the admin
   user.** The DB still held `b2b2683d…`, so the real login kept working and the drifted
   value was dead weight in the env file. Recreating the `grafana_data` volume would have
   adopted the drifted value — which existed only inside codey's docker volume.
2. **The 21:01 deploy was monitor-only** (`--tags user.docker.monitor`). `moodle/db.env`
   (Oct 27), `moodle/config.php` (Oct 27), `pass/.env` (Oct 9) and
   `traefik/dashboard-auth.htpasswd` (Oct 22) were untouched. The same defect is unguarded
   for `vault_moodle_db_*` (a seedless deploy would rotate the Moodle DB credentials) and
   `vaultwarden_admin_token`.

Restic never had this problem because `roles/restic/tasks/seed_guard.yml` hard-fails on a
missing seed *before* the lookup is dereferenced. Grafana, Moodle and the Vaultwarden admin
token have no equivalent guard.

## Decision

1. **Restore the authoritative value through the sanctioned path** — a monitor-only Ansible
   deploy from an up-to-date controller checkout, not a hand-edit of the server file.
2. **Keep an off-host recovery copy in Vaultwarden**, so a controller without the seed can
   recover the real password instead of generating a new one: new play
   `ansible/plays/monitor_vaultwarden.yml` (`--tags monitor.vaultwarden`), modelled on the
   existing `opencode_authgate.yml` → `vaultwarden/tasks/push_items.yml` path.
3. **Document the hazard** in `CLAUDE.md` (seed table + recovery rules), because the next
   operator will hit it the same way.

The seed file stays the source of truth; Vaultwarden is a *copy* (same rule as restic).

## Consequences

### Positive
- `monitor/grafana.env` and the running container env are back to `b2b2683d…`, the value
  Grafana's DB actually holds — env and DB agree again, and a deploy from the original
  controller is idempotent.
- The Grafana admin password is now recoverable from Vaultwarden
  (`grafana - admin (lehel.xyz)`, username `admin`), so a fresh controller can restore the
  seed instead of rotating the credential.
- The "`lookup('password')` seed is controller-local" trap is written down where the next
  deploy will look, including how to tell an env/DB mismatch from a real rotation.

### Negative / Tradeoffs
- The Vaultwarden copy is only as fresh as the last `--tags monitor.vaultwarden` run; it is
  not pushed automatically on deploy (deliberate: the restic push is handler-driven, this
  one is on demand).
- A deploy from any controller that lacks the seed still rotates the env value. Nothing
  prevents it yet; detection is manual (`curl -u admin:<env pw> /api/user`).

### Known issues
- No `seed_guard` equivalent for Grafana, Moodle or the Vaultwarden admin token — only
  restic is protected.
- Grafana logs one benign `Failed to read plugin provisioning files … no such file or
  directory` at boot; `monitor/provisioning/` has no `plugins/` directory. Not fatal, not
  introduced by this change.
- The deploy checkout on `servy` is a git checkout whose three rendered monitor files are
  permanently "modified" against git — see the 2026-10-30 render-trap ADR. This change did
  not touch that.

## Implementation details

**Files modified (repo):**
- `ansible/plays/monitor_vaultwarden.yml` — NEW: push the Grafana admin password to
  Vaultwarden as a Login item (`grafana - admin (<domain>)`, username `admin`), gated on
  `vw_master_password` and `services_enabled.monitor`.
- `ansible/servyy.yml` — MODIFY: `import_playbook: plays/monitor_vaultwarden.yml` (tag
  `monitor.vaultwarden`).
- `CLAUDE.md` — MODIFY: seed row for `.monitor_grafana_admin_password`, row for the new
  playbook, new recovery rule 6 (controller-local seeds / drift hazard).
- `history/2026-11-01_grafana-admin-password-drift.md` — NEW (this file).

**Files modified (server, `/home/cda/servyy-container`):**
- `monitor/grafana.env` — re-rendered from the controller seed (one line).

**Commands:**
```
# controller was 8 commits behind; fast-forwarded first so the monitor templates match
git pull --ff-only
# preview: exactly one line changed
ansible-playbook plays/user.yml -i production --limit servy.lehel.xyz --tags user.docker.monitor --check --diff
# apply
ansible-playbook plays/user.yml -i production --limit servy.lehel.xyz --tags user.docker.monitor
# recovery copy
ansible-playbook servyy.yml -i production --limit servy.lehel.xyz --tags monitor.vaultwarden
```

**Verification performed:**
- `--check --diff` preview: exactly one changed line
  (`GF_SECURITY_ADMIN_PASSWORD`), all three rendered provisioning files `ok`.
- Real run: `ok=14 changed=2 failed=0`; the deploy recreated `monitor.grafana`.
- `monitor/grafana.env` and `docker exec monitor.grafana printenv
  GF_SECURITY_ADMIN_PASSWORD` both hash to `b2b2683d2b5fb940` (== the seed, == the value the
  DB accepts).
- `curl -u admin:<restored pw> http://localhost:3000/api/user` → **200**.
- `docker inspect monitor.grafana` → `running`, `healthy`, `RestartCount=0` (no crash loop).
- Provisioned content intact: **43** alert rules, datasources `Prometheus
  (http://prometheus:9090)` and `Loki (http://loki:3100)`.
- All other monitor containers still up (prometheus, loki, promtail, node-exporter, cadvisor,
  pushgateway).
- Vaultwarden round-trip: `bw list items` shows `grafana - admin (lehel.xyz)`, username
  `admin`, password hash `b2b2683d2b5fb940` — **MATCH** with the controller seed.

**Key learnings:**
1. `lookup('password', 'vars/…')` is not a secret source, it is a **per-controller
   generator**. Every controller that can run the playbook is a potential rotation source.
2. Grafana's admin password lives in `grafana.db`, not in the env: a 401 with the env value
   means "env drifted", not "password was rotated". Test both values before concluding.
3. The drift is provable without any server-side history: the generated seed file keeps the
   mtime of the deploy that created it, and its content matches the rendered file byte for
   byte.
4. `git pull` on the controller matters before a template-driven deploy — a stale checkout
   re-renders stale templates over newer live files.

## Alternatives considered

### Alt A: hand-edit `monitor/grafana.env` on the server
Pros: no controller run, seconds.
Cons: violates the "no manual production edits" rule, bypasses the render path, and leaves
the next deploy to re-apply whatever the controller's seed says.
**Rejected.**

### Alt B: drop `GF_SECURITY_ADMIN_PASSWORD` from the template and manage the password with
`grafana cli admin reset-admin-password`
Pros: removes a value that is a no-op after first init anyway.
Cons: loses the "known credential" property and needs a different recovery story; Grafana
would then have no declarative admin password at all.
**Rejected** — the env value is still the documented credential for a fresh volume.

### Alt C: extend `seed_guard` to every `lookup('password')` secret in the same change
Pros: fixes the whole class (Grafana, Moodle, Vaultwarden token) instead of one instance.
Cons: a structural change to several roles with its own test surface; the immediate drift
was still live in production.
**Rejected for this change** (the drift was restored and the recovery copy exists now);
the missing guard is recorded under Known issues.
