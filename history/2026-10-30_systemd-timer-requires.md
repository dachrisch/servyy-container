# 2026-10-30 — systemd timers no longer run their service at every boot

**Date:** 2026-10-30
**Status:** ✅ Merged (PR #253) and deployed to `servy.lehel.xyz` + `codey.lehel.xyz`
**Relates to:** `2026-10-28_security-audit-trivy-empty-results.md` (the containerd
prune hazard), `.claude/skills/check-server-status/SKILL.md`

## Symptom

A routine health check flagged `kernel-cleanup.timer` as overdue (`LAST = 2026-10-04`,
3½ weeks old) on both hosts — and the same check found `kernel-cleanup.service` had run
**2026-10-29 05:30:47**. Both observations were correct, and they contradicted each other
in a way that pointed at the real bug.

## What was actually going on

1. `kernel-cleanup` and `security-audit` are **monthly** (`OnCalendar=Sun *-*-1..7 …`, first
   Sunday), so a 3–4 week-old `LAST` is normal. The stamp file
   `/var/lib/systemd/timers/stamp-kernel-cleanup.timer` (mtime Oct 4 01:03) confirms it.
2. The service ran anyway because each timer template carried
   `Requires=<same-name>.service` in `[Unit]`. systemd activates the same-name service on
   elapse regardless, so the line was redundant for scheduling — but `Requires=` also pulls
   the service in whenever the **timer unit starts**, including at boot.

Measured before the fix (servy auto-rebooted 2026-10-29 05:30 via unattended-upgrades):

```
kernel-cleanup   last-start = Thu 2026-10-29 05:30:46   ← boot, not 1st Sunday
security-audit   last-start = Thu 2026-10-29 05:31:05   ← boot, not 1st Sunday
docker-cleanup   last-start = Fri 2026-10-30 02:01:14   ← scheduled, correct
```

So every reboot ran an apt kernel cleanup and a full security audit.

## Why it mattered beyond noise

`docker-cleanup.timer` already sets `Persistent=false` with an explicit comment:

> with true, a run missed because the host was rebooting is executed immediately on the next
> boot, while containerd is still settling. That window is where the containerd content store
> lost layer blobs the images still referenced

`Requires=` reintroduced exactly that boot-time prune through a different door — the
protection the `Persistent=false` line was written for was never actually in force.

## Change

Removed `Requires=<service>` from `docker-cleanup.timer.j2`, `kernel-cleanup.timer.j2` and
`security-audit.timer.j2`, each with a comment saying why it must not come back. The
*service* units keep `Requires=docker.service` where they genuinely need it.

## Second finding: codey's docker-cleanup was stale

While verifying, codey's timer still read `OnCalendar=Sun 02:00` + `Persistent=true` — the
pre-2026-10-27 **weekly** schedule — while servy had the current daily `*-*-* 02:00` +
`Persistent=false`. On a 29 GB host that hit 0 bytes free the same day, a weekly prune is the
wrong cadence. The deploy re-rendered it; it is daily now.

Switching that unit also produced one real catch-up run: `docker-cleanup.service` fired
2026-10-30 16:55:28 on codey, because the running instance still had `Persistent=true` and
the schedule change created a backlog of missed daily elapses. It completed `success`
(reclaimed 0 B — nothing unused), all 9 containers stayed up, disk unchanged.

## Verification

- `systemctl cat <timer>` on both hosts: no `Requires=` line in any of the three
- all three timers `active/waiting`; codey's `docker-cleanup` now `OnCalendar=*-*-* 02:00`
- `ExecMainStartTimestamp` for `docker-cleanup` / `kernel-cleanup` / `security-audit` was
  captured **before** the deploy and is **unchanged after it** on servy — the deploy
  (daemon-reload + timer start) started no service, which is the whole point of the fix
- the next reboot is the real proof: nothing should start on it

## Skill update

`check-server-status` (pushed as `a23cf71`, then corrected in this change):

- the enabled-services table was stale — `moodle` and `bnb-office` were missing from servy,
  and `claude-hub` is documented as never having had a container anywhere
- the timer step now carries the real per-unit schedule and says to read `OnCalendar` +
  the stamp file before calling anything late
- the "service journal entry ≠ schedule fired" trap is recorded, with the caveat that the
  `Requires=` cause was removed here so it should no longer happen
