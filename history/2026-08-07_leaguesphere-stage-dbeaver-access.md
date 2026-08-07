# LeagueSphere stage DB access via DBeaver — restricted SSH tunnel

**Date:** 2026-08-07 → 2026-08-08
**Status:** Deployed to production, verified

## Problem

An operator needed ad-hoc DBeaver (GUI) access to LeagueSphere's **stage** database — a
nightly clone of live production data — from a workstation. The starting idea (from an
external AI troubleshooting chat, before any design work here) was to expose the DB
publicly via Traefik. That was rejected during brainstorming: MySQL's wire protocol can't
be SNI-multiplexed onto this repo's shared HTTPS entrypoint the way HTTP(S) services are,
and public exposure would invert security decisions already made deliberately elsewhere in
this infra (prod's `leaguesphere.db` has no published ports; the SSH chroot jail hardcodes
`AllowTcpForwarding no` for the LeagueSphere deploy account specifically to prevent this
class of tunnel).

## Solution

A dedicated, unprivileged Linux account (`dbeaver_stage`) whose sole SSH key is restricted
— via `authorized_keys` (`restrict,port-forwarding,permitopen`, `command="/bin/false"`,
`exclusive: true`) **and** an sshd `Match User` block (`AllowTcpForwarding local`) — to
forward only to a stable, loopback-only port (`127.0.0.1:33062`) that stage's `mysql`
container now publishes. A nightly systemd-timer-driven script keeps stage's data fresh
from prod. Both this new key and the existing LeagueSphere deploy key are backed up to
Vaultwarden via a new shared role generalized from `restic`'s existing mechanism.

Full design: `docs/superpowers/specs/2026-08-07-leaguesphere-stage-dbeaver-access-design.md`
Full plan (with the complete history of every bug found and fixed along the way):
`docs/superpowers/plans/2026-08-07-leaguesphere-stage-dbeaver-access.md`

## Files changed

**`leaguesphere` app repo** (separate repo, PRs #1792 and #1795):
- `deployed/docker-compose.staging.yaml` — `mysql` service publishes `127.0.0.1:33062:3306`,
  on a second dedicated non-internal network (`db_access`) alongside the existing internal
  `backend` — the second network was a follow-up fix, see below.

**This repo** (`servyy-container`, PRs #53–56, merged via `01108f2`):
- New role `ansible/plays/roles/vaultwarden/` — generalized Vaultwarden push mechanism
  (`unlock.yml`, `push_items.yml`), and `restic` migrated onto it (not left as a parallel
  duplicate): `restic/tasks/bw_unlock.yml` deleted, `restic/tasks/vaultwarden_push.yml`
  gutted to a thin `include_tasks` (handlers can't use `include_role` anywhere in their
  execution chain, even transitively), `restic/tasks/seed_guard.yml` and
  `restic/defaults/main.yml` updated accordingly.
- New role `ansible/plays/roles/ls_dbeaver_access/` — the `dbeaver_stage` account, its
  restricted key, and the sshd Match block, gated to `['lehel.xyz', 'servyy-test.lxd']`.
- `ansible/plays/roles/ls_db_sync/` — new role-local `templates/oneshot.{service,timer}.j2`
  + `tasks/oneshot_include.yml` (own copies, not a cross-role reference to `restic`'s — see
  below), new `templates/ls_db_sync.sh.j2` (the nightly script) and `tasks/timer.yml`.
- `ansible/plays/leaguesphere.yml` — `vw_master_password` vars_prompt, `ls_dbeaver_access`
  role invocation.

## Deployment results

Deployed and verified on `servyy-test.lxd` first (Task 6), then `lehel.xyz` (Task 7), both
`failed=0` across all tags. Both environments verified end-to-end:
- Loopback port confirmed listening (`127.0.0.1:33062`, not `0.0.0.0`).
- Tunnel + DB connection works (`SELECT 1` → `1`).
- Forwarding to any other destination is rejected by sshd (`administratively prohibited`).
- The account cannot obtain a shell.
- The nightly sync script runs successfully on demand.
- `restic`'s migrated Vaultwarden code (the disaster-recovery password-restore path) still
  works.

## Verification commands

```bash
# Loopback port
ssh <host> "ss -tlnp | grep 33062"

# Tunnel + DB
ssh -i ~/.ssh/dbeaver_stage_key_<host_short> -L 3307:127.0.0.1:33062 dbeaver_stage@<host> -N -f
mariadb -h 127.0.0.1 -P 3307 -u leaguesphere_stage -p'<password>' leaguesphere_stage -e "SELECT 1;"

# Disallowed forward (expect "administratively prohibited")
ssh -i ~/.ssh/dbeaver_stage_key_<host_short> -L 3308:127.0.0.1:3306 dbeaver_stage@<host> -N -f
nc -zv 127.0.0.1 3308

# No shell (expect "This account is currently not available")
ssh -i ~/.ssh/dbeaver_stage_key_<host_short> dbeaver_stage@<host>

# Nightly sync
ssh <host> "systemctl --user start ls-db-sync-nightly.service && systemctl --user status ls-db-sync-nightly.service --no-pager"

# restic regression
./servyy.sh --tags restic.init --limit <host>
```

## DBeaver client configuration

| Tab | Field | Value |
|---|---|---|
| SSH | Host | `lehel.xyz` |
| SSH | User | `dbeaver_stage` |
| SSH | Auth | `~/.ssh/dbeaver_stage_key_lehel` |
| Main | Host | `127.0.0.1` |
| Main | Port | `33062` |
| Main | Database / User | `leaguesphere_stage` / `leaguesphere_stage` (password in `ansible/plays/roles/ls_app/vars/secret_stage.yaml`) |

## Real bugs found by actually deploying (not by task review or the final whole-branch review)

This is the significant part of this feature's history — five genuine, deployment-only-visible
bugs surfaced during Task 6/7, none catchable by `--syntax-check`, `--list-tasks`, or code
review alone:

1. **`include_role` illegal transitively from a handler, not just when written directly in
   one.** The first fix for the "handlers can't use `include_role`" restriction (found in the
   final whole-branch review) was itself still wrong — a wrapper reached via `include_tasks`
   that then did `include_role` still failed. Corrected to a plain `include_tasks` with no
   `include_role` anywhere in the chain.
2. **Cross-role `import_tasks` doesn't resolve templates correctly.** `ls_db_sync/tasks/timer.yml`
   originally reused `restic`'s `oneshot_include.yml` by path; Ansible's `template:` module
   resolves a bare `src:` relative to the *importing* role's own `templates/`, never the
   owning role's — so `restic/templates/oneshot.service.j2` was never found. Fixed with
   role-local copies (matching the existing precedent in `roles/user/`).
3. **Host-guard mistranscription.** The final reviewer's own suggested fix for "no host guard"
   was `['lehel.xyz', 'servyy-test.lxd']` — deliberately including the test box. Writing it
   into the plan dropped the test host, making the role untestable until Task 6 caught it.
4. **`ls_db_sync`'s on-demand sync shares a tag with the stage-deploy tag.** `--tags
   ls.app.stage` also triggers `ls_db_sync`'s on-demand sync, which needs prod's local DB
   container — fine on `lehel.xyz`, but `servyy-test.lxd` has no such container. Test deploys
   need `--skip-tags ls.db.sync`.
5. **Docker Compose doesn't publish ports on `internal: true`-only networks.** Compose 2.40.3
   silently accepts a `ports:` binding into the container config but never activates it if the
   service's only network is `internal: true` — reproduced with a minimal, unrelated test case.
   Fixed with a second, dedicated non-internal network for `mysql` (leaguesphere PR #1795).
6. **Nightly script needed an explicit `-h 127.0.0.1`.** Without it, the MariaDB client falls
   back to a `MYSQL_HOST` env var if one happens to be set inside the container's own
   environment — a stale `MYSQL_HOST=s207.goserver.host` on an unrelated leftover test
   container caused a real failure. The pre-existing on-demand sync task has this same gap,
   left untouched (out of scope), but flagged.
7. **`ansible-lint` can't resolve `{{ playbook_dir }}` when linting a role in isolation.** CI's
   `production`-profile lint failed on the C1 fix's `{{ playbook_dir }}`-based path — works
   correctly at real runtime, but lint computes the wrong path when statically analyzing a
   role outside playbook context, and the resulting violation can't be suppressed with an
   inline `# noqa` (it's anchored to the wrong synthetic path). Fixed with a plain relative
   path, which needs no Jinja evaluation.

## Known issues / follow-ups

- **I1 (partially mitigated, not architecturally fixed):** the shared `vaultwarden` role uses
  `run_once: true`, which `ansible-core` documents as unsupported under `leaguesphere.yml`'s
  `strategy: free`. The host guard (fix #3 above) makes this a non-issue in practice today
  (only one host at a time ever matches), but the underlying mismatch remains latent for any
  future `strategy: free` caller that needs multi-host reach.
- **Pre-existing `ls_db_sync` on-demand sync** has the same missing-`-h` fragility as bug #6,
  left unfixed (out of scope for this feature).
- Vaultwarden push was not exercised on either `servyy-test.lxd` or `lehel.xyz` during this
  deployment (master password not supplied) — re-run `./servyy.sh --tags ls.dbeaver --limit
  lehel.xyz` with the password to back up both keys.
