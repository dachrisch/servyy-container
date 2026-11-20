# 2026-11-20 — codey upgraded to Ubuntu 26.04 LTS

## Context

`codey.lehel.xyz` — the Oracle Always Free A1 instance (`oracle-codey`, 2 OCPU /
12 GB / 100 GB, aarch64) that runs the OpenCode server, its authgate, Traefik and
the Grafana/Loki half of the monitor stack — was still on **Ubuntu 24.04.5**
while `servy` had been on **26.04.1** for months. Two LTS releases in the fleet
means two sets of package versions, two fail2ban/OpenSSH behaviours and an
upgrade debt that grows with every month the old release stays.

`do-release-upgrade -c` already offered `26.04.1 LTS` (the LTS→LTS path has been
open since 26.04.1), and servy runs the same Ansible roles on 26.04 — so this
was a first-time-for-this-host step, not a first-time-for-the-config step.

## Decision

**In-place `do-release-upgrade`**, not a blue/green replacement. A second A1
instance plus its boot volume would put the tenancy's 200 GB Always Free block
storage over the limit (the current boot volume alone is 100 GB), and opencode's
state lives in a Docker volume that would have to be migrated anyway.

**No OCI boot-volume backup** — deliberate, chosen by the operator. The rollback
story is therefore "rebuild on the 26.04 image + Ansible + restic restore"
(~30–60 min), not a volume swap. Everything that makes that possible was
verified *before* the upgrade, not assumed:

- restic root snapshot `07072eed` (11:35:48) — the **first** snapshot to contain
  `monitor_grafana_data` and `monitor_loki_data`, because Grafana/Loki only moved
  to codey at 00:05+ earlier that day. Checked with
  `restic ls latest /var/lib/docker/volumes` rather than trusting the schedule.
- pre-upgrade manifest in `/tmp/opencode/codey-pre-upgrade/` (`dpkg
  --get-selections`, `docker ps -a`, `docker volume ls`, enabled units, `/etc`
  tarball) and the recovery coordinates (instance, boot volume, console
  connection OCIDs).
- an OCI **console connection**, so a host that does not come back is
  diagnosable without the web console.

`codey_dev_checkouts` (~6.6 GB) stays excluded from the root snapshot by
design — rebuildable, but uncommitted work there has no safety net (pre-existing).

## What was done

### Host

1. 24.04 fully patched first (`apt-get full-upgrade`, only `python3-jwt` pending).
2. `apt-daily.timer`, `apt-daily-upgrade.timer` and `unattended-upgrades.service`
   runtime-masked — `50unattended-upgrades` has `Automatic-Reboot "true"` at
   05:30, which would have rebooted the box mid-upgrade.
3. `do-release-upgrade -f DistUpgradeViewNonInteractive` in a detached tmux
   session (an SSH drop must not kill the upgrader), log at
   `/root/dist-upgrade-run.log`. `EXIT=0`.
4. The noninteractive frontend does **not** reboot; the box was still running the
   old kernel afterwards. Rebooted deliberately once GRUB was confirmed to point
   at the 26.04 kernel.
5. Ansible reconcile (`./servyy.sh --limit codey.lehel.xyz`) to let the roles
   converge the host rather than hand-fixing what the upgrade left behind.

Timeline: 11:38 start → 11:52 `EXIT=0` → 11:53 reboot → SSH back in 25 s.

### Repository

- `scripts/provision-oracle-codey.sh` — `IMAGE` repointed from the 24.04 aarch64
  image to `Canonical-Ubuntu-26.04-aarch64-2026.11.05-0`
  (`ocid1.image.oc1.eu-frankfurt-1.aaaaaaaahl2jtz24uqnqntt5vliczqo6ewnkqoy5oct24t72sdzkolyd3dea`).
  Without this, a rebuild from the script would silently re-provision 24.04.
- `architecture/landscape.yaml` — codey's `os` field `24.04` → `26.04`, disk
  figure refreshed to the measured 28 %. `render.py --verify` silent before and
  after (30 services, 45 edges).
- `ansible/plays/roles/system/templates/fail2ban/` — both blocklist service
  units order after `docker.service`, and the script retries its Loki readiness
  probe (finding 2).
- `ansible/plays/user.yml` — the two `searxng` tasks are gated on the service
  being enabled for the host (finding 3).
- `ansible/plays/roles/restic/tasks/init.yml` — the initialise loop is labelled
  by repository, so the passwords stop appearing in deploy logs (finding 4).

## Verification

| Check | Result |
|---|---|
| `/etc/os-release` | `Ubuntu 26.04.1 LTS` |
| Kernel | `7.0.0-1016-oracle` (26.04 build), default GRUB entry |
| IPv6 | static `2603:c020:802e:5f01:0:876f:f045:3504/128` + `::/0 via fe80::200:17ff:fecf:724` intact, `ping6` from servy 0 % loss |
| netplan | `50-cloud-init.yaml` and `60-ipv6.yaml` untouched (Nov 17 mtimes); MTU 9000 preserved |
| Containers | 10/10 Up, `unless-stopped` survived the reboot |
| fail2ban | 3 jails (`loki-blocklist`, `sshd`, `sshd-invalid-user`) — the unit-wide `_SYSTEMD_UNIT=ssh.service` journalmatch already covers OpenSSH 10, which codey now runs |
| monit | 5.35.2 (upgraded from 5.33.0), every row OK |
| Routing | `code.lehel.xyz` 200 (v4 and v6), `traefik.code` 401, `monitor.lehel.xyz` 302 |
| Timers | `apt-daily-upgrade`, `docker-cleanup`, `restic-forget`, `restic-check`, `kernel-cleanup` all scheduled; restic user timers (`restic-backup-home` hourly, `restic-backup-root` daily) alive |

**Ansible reconcile:** `./servyy.sh --limit codey.lehel.xyz` now runs end to end
instead of aborting at the first Vaultwarden push — 12 plays (`system`, `user`,
`opencode`, `docker services`, `portainer`, both Vaultwarden pushes, `restic`,
`restore drills`, `leaguesphere`, `testing`), `ok=624`, `failed=0`, 23 changed
(the repo's usual always-changed render/download tasks), 4 ignored (the
storagebox timer, which codey does not have by design, and the `searxng`
compose enumeration for a service this host does not run). The five pushes in
that run all synced at rc=0 with the repair block skipped and every item
`unchanged`.

Ubuntu Pro's ESM sources were rewritten to `resolute-*` by the upgrader and the
Trivy apt repo, which do-release-upgrade disables as third-party, was re-added by
the `system` role.

## Findings made during this work

1. **`bw sync` aborted full `servyy.sh` runs — root-caused and fixed here.**
   Both full runs died at `vaultwarden : Sync vault` (`unlock.yml`, `no_log`
   censoring the reason), in *different* plays — opencode's push in run 1,
   Grafana's in run 2 — while a third full run passed with every sync at rc=0.
   The variable was the **age of the CLI's access token**:

   - The token is a JWT with a **2 h TTL** (measured: `exp` minus
     `global_account_activity` for the live state).
   - `bw login --apikey` is a **no-op when the CLI already holds a token**
     ("already logged in", rc=1, which the role tolerated), so nothing ever
     minted a new one. `bw unlock` is purely local and kept succeeding.
   - `bw sync` needs the API; against an expired token it tries to refresh, and
     this Vaultwarden **rejects the refresh with `invalid_grant` (400)** for a
     `client_credentials` login. Proved with `bw sync --force` (which always
     refreshes) on a *just-logged-in* state, on both the real CLI state and a
     copy with the orphan account record removed — so the orphan record was not
     the cause. The CLI then dies with `ERR_UNHANDLED_REJECTION` (Node 22).

   Consequence: any run reaching a Vaultwarden push more than 2 h after the last
   real login aborted, taking the `restic`, `restore_drill`, `leaguesphere` and
   `testing` plays with it. The upgrade is unrelated.

   Fix, in `plays/roles/vaultwarden/tasks/unlock.yml` (+118 lines, no task
   behaviour changed on the happy path):

   - **`bw sync` is no longer fatal.** It is registered with
     `failed_when: false`, so a failed cache refresh can never abort a deploy
     again — every push in the role writes to the server directly.
   - **The login is rebuilt reactively**, only when the sync actually fails:
     `bw logout` → `bw config server` → `bw login --apikey` → `bw unlock` →
     `bw sync` again, adopting the new session. A first attempt put
     `bw logout` unconditionally in front of every push; that was rejected
     because it changes a path that has worked since August for no gain — the
     repair belongs on the failure, not the success.
   - **`bw lock` before every unlock.** `bw unlock` against a locally cached
     *unlocked* vault exits 0 and prints **nothing**; the role read that as
     "empty password" and failed the play. Locking first guarantees a real
     decrypt, and the unlock now retries up to 3× when it gets rc=0 with empty
     stdout (a wrong password returns rc≠0 and stops the retry immediately, so
     Vaultwarden's rate limit is not at risk). The failure was intermittent —
     one full run died on its third (handler) push while an identical run of the
     same code passed minutes later — and this makes the start state
     deterministic instead of depending on what the previous push left behind.

   Verified: full `servyy.sh --limit codey.lehel.xyz` runs complete (see
   Verification), the push play reports `unchanged`/`created` as before, and the
   repair block stays skipped in the normal case. `bw sync --force` remains
   broken by design against this server and must never be used.
2. **`update-blocklist-quick.service` failed once at boot — fixed.** It started
   with `fail2ban.service` and probed Loki in its first second; on the hosts that
   run the monitoring UI, Loki is a **container** behind local Traefik, so
   `docker.service` being up says nothing about readiness, and the single
   `curl …/ready` probe marked the unit `failed` on every reboot. Both blocklist
   units now order after `docker.service` (`After=` + `Wants=`) and the script
   retries the probe 12 × 5 s before declaring Loki down — 55 s of retries still
   fails the unit when Loki is genuinely unreachable or the credential is
   rejected, just a minute later. The retry matters on servy too, where Loki is
   remote and docker ordering proves nothing.
3. **`Stop searxng before config update` failed on codey — fixed.** The task ran
   on every host, so on a host that does not deploy searxng `docker compose`
   answered `env file …/searxng/.env not found` and the task failed (ignored,
   which is worse: it buried real failures in the same loop). Both searxng tasks
   are now gated on `'searxng' in services`; `ignore_errors` stays because on a
   *first* deploy the `.env` is rendered later in the same play.
4. **Both restic repository passwords were printed in every deploy log — fixed.**
   `restic : Initialize restic repositories` loops `restic_repos_enabled`, and
   the loop item carries `password`; without `loop_control` Ansible prints the
   whole item dict, so every deploy wrote both passwords in plaintext (found in
   these upgrade runs). The task now labels each item by `item.repository`, like
   the `Verify … opens with the configured password` task always did. Any
   operator log or CI transcript from before this change contains those two
   passwords — rotate them if such a log was shared.

## Rollback (not needed)

Rebuild `oracle-codey` from the 26.04 image, run `./servyy.sh --limit
codey.lehel.xyz`, then restore the root repo
`sftp://storagebox/backup/oracle-codey.lehel.xyz/restic-root` (snapshot
`07072eed`). The public IPv4/IPv6 live on the VNIC, so DNS is untouched. Old
`6.8.0-*` kernels were removed by the upgrader itself; the two remaining
`7.0.0-*` oracle kernels are reaped by the monthly `kernel-cleanup` timer.
