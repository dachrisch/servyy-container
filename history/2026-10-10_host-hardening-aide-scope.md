# Host Hardening AIDE Scope Fix — 2026-10-10

## Problem

The P6 AIDE init (PR #201, fixed for its config path in #205) never completed on
`servy.lehel.xyz`: `aide --init` ran for >45 min and had to be aborted. Cause: the
distro baseline `/etc/aide/aide.conf` (aide-common) selects `/` with the `Full` attribute
set, so it scans the whole 60 G root — including `/mnt` (network storage), `/var/lib`
data and `/home` — while computing ~9 hashes per file.

Two concurrent runs were also left behind by the aborted attempts, both writing
`/var/lib/aide/aide.db.new`.

## Solution

Deploy a scoped AIDE config (`/etc/aide/aide-hardening.conf`) instead of the distro
baseline:

- Monitors system-integrity roots only (`/boot /etc /bin /sbin /lib /lib64 /usr /opt
  /root /var/spool`); excludes `/mnt /media /home /srv /tmp /var/{tmp,log,cache,lib,backups}
  /proc /sys /dev /run`.
- Uses `sha256+sha512` (not the 9-hash `Full`).
- Uses its own database paths (`/var/lib/aide/aide-hardening.db[.new]`) so it does not
  collide with the pre-existing `dailyaidecheck.timer`, which keeps using the distro
  config and `/var/lib/aide/aide.db`.

`tasks/hardening.yml` deploys the config and points both the init task and
`aide-check.service` at it; the init `creates:` guard and `mv` target track the new DB
filename.

## Validation

- `aide --config /etc/aide/aide-hardening.conf --config-check` → rc 0.
- `aide --init` with the scoped config: **2 m 18 s**, 9.4 MB DB (vs. >45 min, no DB).
- `ansible-playbook plays/system.yml --syntax-check` ✅; ansible-lint ✅; yamllint ✅.

## Follow-up

- `dailyaidecheck.timer` (daily, aide-common) still runs the heavy distro config against
  `/var/lib/aide/aide.db`; consider pointing it at the scoped config or disabling it in
  favour of the weekly `aide-check.timer`.
