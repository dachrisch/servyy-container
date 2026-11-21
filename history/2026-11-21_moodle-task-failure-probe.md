# Alerting on Moodle task failures (the blind spot behind the Ghostscript incident)

**Date:** 2026-11-21
**Service:** `moodle.moodle` (offd.de) + the monitor stack
**Trigger:** the 2026-11-21 conversion failure
([history](2026-11-21_moodle-editpdf-ghostscript.md)) was reported by Moodle's own admin mail
("Die Task … ist mehrmals fehlgeschlagen"), never by monitoring — 20 failed runs and five parked
student submissions over two days, with a green dashboard the whole time.

## Why nothing saw it

Two independent reasons, and both had to be fixed by reading the database:

1. **The image sends cron output to `/dev/nulll`** (typo in its runit script), so a failing task
   leaves nothing in `docker logs` — log-freshness and Loki alerting are blind to it.
2. **The container stays `healthy`**: nginx and php-fpm are fine, the failures live in
   `mdl_task_log` (`result <> 0`) and in Moodle's retry state — `mdl_task_adhoc.faildelay` /
   `attemptsavailable`, `mdl_task_scheduled.faildelay`. `attemptsavailable = 0` is Moodle's
   "stopped retrying, a human must look" flag, i.e. exactly the state the admin mail describes.

## What was added

**Probe** `ansible/plays/roles/system_probe/templates/moodle_task_failures.sh.j2` →
`~/.system-probes/moodle-task-failures.sh`, timer `system-moodle-tasks.timer` every 5 minutes,
deployed only where `moodle_enabled` **and** the Pushgateway sink exists (servy). It runs
`php` **inside the container** via `docker exec -i` (a heredoc on stdin, no temp file in the
immutable docroot, no DB credentials on the host) and pushes:

| series | meaning |
|---|---|
| `moodle_task_failures{window="1h"}` | failed runs (`mdl_task_log.result <> 0`) in the window |
| `moodle_task_failure_threshold{window="1h"}` | tolerated count, default **1** (2+ pages) |
| `moodle_task_needs_attention` | parked ad-hoc tasks (`attemptsavailable = 0`) + scheduled tasks with `faildelay > 0` |
| `moodle_task_needs_attention_threshold` | default **0** — one parked task pages |
| `moodle_task_probe_success` | 0 = could not read Moodle (container down, DB unreachable, PHP broken) |

Thresholds live in `system_probe/defaults/main.yml` (`system_probe_moodle_*`) and travel as
series, because the alert file is static — the same lesson as the restic/dump rules
(monitor/AGENTS.md invariant 5). A failed read pushes `-1` for the counts, which the rules turn
into a hit through `< bool 0` (a raw `-1` compares as "not met" in Grafana).

**Alert rules** `monitor/provisioning/alerting/alert-rules.yml`, group `moodle-alerts`:

| uid | severity | condition |
|---|---|---|
| `moodle_task_needs_attention` | high, `for 5m` | parked/failing tasks > 0 |
| `moodle_task_failures` | medium, `for 30m` | 2+ failed runs in the hour |
| `moodle_task_probe_failure` | medium, `for 20m` | probe cannot read Moodle |
| `moodle_task_probe_stale` | medium | no push for 30 min (timer dead) |

Runbook text is in each rule's `description` (status report → "Task failed multiple times",
`mdl_task_log.output`, and how to requeue a parked task). Molecule (`system_probe/default`)
covers script deployment and pins the emission lines; `monitor/AGENTS.md` and `moodle/AGENTS.md`
document the probe and the requeue recipe.

## Verification

- `bash ~/.system-probes/moodle-task-failures.sh` → `probe_success=1 failed_1h=0 parked=0
  scheduled_failed=0`; the Pushgateway then carries all five series
  (`curl 127.0.0.1:9091/metrics | grep '^moodle_'`) and Prometheus serves
  `moodle_task_needs_attention{job="moodle_task_failures"} 0`.
- The rules evaluate (health `ok`, no data = OK) and were proven in both directions by pushing a
  synthetic `1` into the same job, seeing `moodle_task_needs_attention` fire, and letting the next
  real probe run overwrite it back to `0` (PUT replaces the whole job group).
