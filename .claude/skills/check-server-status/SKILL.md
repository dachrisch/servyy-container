---
name: check-server-status
description: Use when asked whether servy.lehel.xyz and/or codey.lehel.xyz (or "servy"/"codey"/"the servers") are up, healthy, or running, when doing a general infrastructure health check, or as a smoke test before/after a deployment.
---

# Check Server Status

## Overview

servyy-container runs on two hosts with different roles and different
enabled-service lists (`ansible/production`). "Status" means: is each host
reachable, are its expected containers actually running (not restarting/
exited), is Traefik routing HTTPS traffic to them, is there enough disk/
memory headroom, and are the background jobs (backups, cleanup, security)
still firing on schedule. Checking only `docker ps` misses routing and
resource-exhaustion failures; checking only HTTP misses a crashed container
that Traefik is still fronting with a stale connection.

## The two hosts

| Host | Alias | Role | Enabled services (source of truth: `ansible/production`) |
|---|---|---|---|
| `servy.lehel.xyz` | `lehel.xyz` | Primary | traefik, git, photoprism, bumbleflies (www/bnb/edu/live — repository/archive retired 2026-09-27), achim-hoefer, portainer, pass, energy, groceries, leagues-finance, finance (firefly/importer/queen), shared (mongo/valkey/postgres), bnb-office, searxng, dontforget, **monitor**, leaguesphere (+ demo/stage), **moodle** — disabled: thore, platzler-heid, dns, me, job-search (retired 2026-10-27) |
| `codey.lehel.xyz` | `code.lehel.xyz` | Secondary (opencode) | traefik, opencode, opencode-authgate, portainer-agent, devhub — disabled: claude-hub (its compose dir exists on the test host but **no container has ever run**, so a missing `claude-hub.*` is expected, not a finding) |

Re-grep `ansible/production` (`services_enabled:` per host) before trusting
this table — it drifts as services are added/removed.

## Procedure

1. Run `check-status.sh <host>` for each host you need (see below). It's
   read-only — safe to run any time, no approval needed.
2. Read the "containers NOT Up" section first — that's the crash-loop/exited/
   unhealthy list. Anything there is a concrete finding; an empty running-container
   list or a docker command that errors means the host itself is unreachable.
3. Cross-check the running container names against the enabled-services table
   above — a service listed as enabled but with no matching container is a
   finding even if nothing is "down" per se (deploy that never ran, or was
   silently rolled back).
4. Read the HTTPS routing line(s) at the bottom. These run from wherever you
   invoke the script (not from the target host), so they exercise the real
   public DNS + TLS + Traefik path.
5. Note disk/memory: flag `df -h /` above ~90% used, or `free -h` available
   memory in the low hundreds of MB with no swap headroom.
6. fail2ban should list 3 jails (`loki-blocklist`, `sshd`, `sshd-invalid-user`)
   on both hosts; monit summary should show every row `OK`.
7. Timers: **check the schedule before calling anything late.** Half of them are
   monthly, so a 3–4 week-old `LAST` is exactly right:

   | unit | schedule | hosts |
   |---|---|---|
   | `apt-daily-upgrade` | daily 05:00 (auto-reboot at 05:30 if a reboot is required) | both |
   | `restic-forget` | daily ~05:05 | both |
   | `docker-cleanup` | daily 02:00 (repo default) | both — **codey was still weekly until at least 2026-10-30** |
   | `restic-check` | weekly, Sunday | both |
   | `kernel-cleanup` | **monthly**, 1st Sunday 01:00 | both |
   | `security-audit` | **monthly**, 1st Sunday 04:00 | both |

   `systemctl list-timers --all` `LAST` is accurate — it only *looks* stale for the
   monthly ones. Read `systemctl cat <timer>` for `OnCalendar` and compare
   `/var/lib/systemd/timers/stamp-<timer>` (mtime = last scheduled trigger) before
   flagging anything.

   **A service journal entry is not proof its schedule fired.** These timer templates
   carry `Requires=<service>` in `[Unit]`, so systemd starts the service whenever the
   timer unit starts — which is **every boot**. Measured 2026-10-30: `kernel-cleanup.service`
   ran 2026-10-29 05:30:47, seconds after the unattended-upgrade reboot, while the timer's
   `LAST` correctly stayed 2026-10-04. Consequences worth knowing: `kernel-cleanup` (an apt
   run) and `security-audit` (a full audit) execute on every reboot, and for
   `docker-cleanup` this defeats the `Persistent=false` reasoning in its own template — the
   boot-time prune it was written to avoid still happens.
8. Summarize per host as UP / DEGRADED / DOWN with the specific evidence line
   — don't just say "looks fine."

## Running it

```bash
.claude/skills/check-server-status/check-status.sh servy.lehel.xyz
.claude/skills/check-server-status/check-status.sh codey.lehel.xyz
```

Run both when the user just says "check the servers" — they're separate
hosts with separate failure domains; one being fine says nothing about the
other.

## Reading HTTP codes from the routing check

`monitor` and the dashboards behind basic auth don't return 200 on their
root path. Only `000` (connection failed/timeout) or `502`/`503`/`504`
(Traefik up, backend dead) mean something is actually broken:

| Code | Meaning here |
|---|---|
| `401` | Traefik + backend both alive; endpoint is behind basic auth (traefik dashboard, opencode authgate) |
| `404` | Traefik + backend alive; just no handler at `/` (e.g. Grafana root) |
| `502`/`503`/`504` | Traefik is up, the backend container is not — real finding |
| `000` | DNS/TLS/connection failure — check DNS and Traefik container itself |

## Manual equivalent (if the script isn't available, e.g. from a subagent without repo access)

```bash
ssh <host> "uptime; df -h /; free -h; docker ps -a --format '{{.Names}}\t{{.Status}}'"
ssh <host> "sudo fail2ban-client status; sudo monit summary"
ssh <host> "systemctl list-timers --all | grep -E 'apt-daily-upgrade|docker-cleanup|kernel-cleanup|restic-forget|restic-check'"
curl -s -o /dev/null -w '%{http_code}\n' https://traefik.lehel.xyz   # or https://code.lehel.xyz for codey
```

## Common mistakes

- **Checking `docker ps` without `-a`.** Exited/crash-looping containers
  don't show up in the plain `docker ps` list — always check the "not Up"
  view too.
- **Treating a monthly timer as overdue.** `kernel-cleanup` and `security-audit` run on
  the **first Sunday of the month**, so their `LAST` is legitimately weeks old. Read
  `OnCalendar` before judging (step 7).
- **Reading a service journal as proof the timer fired.** `Requires=<service>` makes the
  service start at every boot, so `journalctl -u kernel-cleanup` shows runs the schedule
  never triggered. `/var/lib/systemd/timers/stamp-<timer>` is the authoritative last
  scheduled run.
- **Treating non-200 as down.** See the HTTP code table above; 401/404 on a
  Traefik-fronted URL is normal for several of these services.
- **Only checking one host.** servy and codey have independent Docker
  daemons, independent disks, independent fail2ban/monit instances — a
  problem on one tells you nothing about the other.
- **Expecting `monitor.*` containers on codey.** The observability stack
  (Grafana/Prometheus/Loki) is only enabled on servy per `ansible/production`;
  its absence on codey is expected, not a finding.
- **Needing root.** `docker ps`, `fail2ban-client status`, and `monit
  summary` all work over a plain `ssh <host>` as `cda` (passwordless sudo is
  configured for the latter two) — no need to `ssh root@...` just to check
  status, even though codey's inventory entry sets `ansible_user: root` for
  Ansible's own bootstrap use.

## See also

- `CLAUDE.md` → "Deployment Verification Checklist" for the fuller
  post-deployment check (includes Traefik/journal log greps this skill
  doesn't run by default).
- `@agent-service-master` for turning a finding here into an actual fix.
