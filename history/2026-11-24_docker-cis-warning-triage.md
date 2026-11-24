# ADR: Triage the Docker Bench warnings from the 2026-11-24 audits

**Date:** 2026-11-24
**Status:** Accepted

## Context

The 2026-11-24 security audits ran Docker Bench for Security v1.6.1 on both production
hosts. Neither host produced a single FAIL:

| Host | Checks | WARN | FAIL |
|---|---|---|---|
| `codey.lehel.xyz` | 117 | 149 | 0 |
| `servy.lehel.xyz` | 105 | ~427 (log is ANSI-coloured; counts taken after stripping escape sequences) | 0 |

The WARN volume looks alarming but is mostly Docker Bench reporting what it cannot see
rather than a container defect: it inspects image defaults and runtime flags without
knowing that a socket mount is the point of Portainer, that 80/443 belong to the edge
proxy, or that an entrypoint may need root to drop privileges. Treating all ~576 WARN
instances across both hosts as bugs would mean rewriting most of the stack for no
security gain. These are WARN instances emitted per container across a few recurring
clusters, not 576 distinct findings; separately, the hosts ran different check suites
(117 checks on codey vs 105 on servy), so the per-host counts are not directly
comparable. Several of the "fixes" would break the services outright.

The recurring warning clusters, with the affected containers, were:

- **Running as root** — on codey: `traefik.traefik`, `runny.dind`, `portainer.agent`,
  `opencode.web`, `opencode-authgate.authgate`. On servy: `portainer.{watchtower-prod,
  watchtower-dev,ofelia,portainer}`, `shared.redis`, `searxng.core`, `pass.pass`,
  `monitor.{pushgateway-bridge,promtail,cadvisor}`, the `leaguesphere*`/
  `leaguesphere-demo` web/db/tunnel containers, `leagues-finance.finance-api`,
  `groceries`, `energy`, the `db-private`/`db-business`/`db-nonprod` MariaDB and Mongo
  containers, `bnb-office.web`, `achim-hoefer.www`, and `bumbleflies.{www,edu,bnb}`.
- **Docker socket mounted** — Portainer, Ofelia and watchtower need the host socket by
  design. Codey's `runny.dind` is a privileged nested daemon with its own socket on a
  `dind-sock` volume at `/var/run/dind`, deliberately not `/var/run/docker.sock`.
- **Privileged ports plus wildcard bind** — 80/443 on `traefik.traefik`, the edge by design.
- **No SecurityOptions / no-new-privileges** — many containers. `PR_SET_NO_NEW_PRIVS`
  blocks privilege *gain* at `execve()` (setuid/setgid bits, file capabilities), not a
  root process's downward `setuid()`; a `gosu`/`su-exec` drop is unaffected. Some images
  do use `su`/`sudo`/setuid helpers, though, so per-container testing is required and
  the flag is out of scope for this narrow pilot. The `www` service sets `PUID`/`PGID`,
  so its entrypoint very likely uses `su-exec`/`gosu`.
- **Root filesystem mounted R/W, no CPU/memory limits, restart policy not `on-failure:5`**
  — deliberate across this stack (`unless-stopped` is the chosen restart policy).
- **Missing healthcheck on the image** — several images; some already have compose overrides.
- **PIDs limit / init process unset** — low-risk and actionable.

## Decision table

| Cluster | Decision | Reason |
|---|---|---|
| Running as root (vendor images: mariadb, mongo, redis, grafana, traefik, plus the containers listed above) | accepted | image default; changing the UID breaks data permissions and the entrypoints |
| Docker socket mounted (Portainer, Ofelia, watchtower; codey's runner/dind is a privileged nested daemon with its own socket) | accepted | the socket clients need it by design; dind deliberately uses its own socket |
| Privileged ports 80/443 + wildcard bind on `traefik.traefik` | accepted | Traefik is the edge; only 80/443 are published on the host |
| Root FS mounted R/W, no CPU/memory limits, restart policy `unless-stopped` rather than `on-failure:5` | accepted | apps need writable roots; undersized limits caused OOM and were raised, so limits are right-sized where present and the rest are case-by-case; the restart policy is deliberate |
| No SecurityOptions / `no-new-privileges` | accepted for now | blocks privilege gain at `execve()`, not downward UID drops; some images use `su`/`sudo`/setuid helpers, so per-container testing is needed and it is out of scope for this pilot (`www` sets `PUID`/`PGID` and very likely uses `su-exec`/`gosu`) |
| PIDs limit / init process | **actionable** | low-risk, testable, no effect on the privilege model |
| Healthcheck missing on image | accepted | image-level finding, not a compose defect; several already have compose overrides |

## Decision

Document the accepted exceptions in this register and change nothing else. The only
warnings carried forward are **PIDs limit and init process**, applied as a narrowly scoped
pilot (`pids_limit: 512` and `init: true` on the four `bumbleflies` services) in a later
task, tested on `servyy-test.lxd` before any production rollout.

The following are explicitly **out of scope** and are not to be "fixed" as part of this
triage:

- `no-new-privileges` — some images use `su`/`sudo`/setuid helpers, so enabling it needs
  per-container testing; out of scope for this pilot (a plain `gosu`/`su-exec` downward
  drop is unaffected).
- CPU and memory limits — undersized limits caused OOM kills and were raised; limits are
  right-sized where present, and each currently unbounded container is a case-by-case
  decision.
- read-only root filesystem — the apps need writable roots.
- user-namespace remap — outside this plan and incompatible with the shared data services.

**No container changes are made in this task.** This ADR records the decision only; the
compose pilot, test-host verification, production rollout and before/after WARN counts are
tracked in the follow-up tasks of the implementation plan.

## Consequences

Positive:

- The zero-FAIL result is preserved in a durable record, and the reason each WARN class is
  tolerated is auditable rather than re-litigated at the next audit.
- Effort is focused on the two genuinely low-risk controls instead of a disruptive
  rewrite that would require testing every entrypoint or re-sizing limits across the
  shared data services.
- The pilot gives a measured WARN delta on a single statics service before any wider change.

Negative:

- The accepted exceptions remain visible in every future audit; the WARN count stays high
  and a future reader must consult this ADR to tell accepted noise from regressions.
- A new service added outside the documented patterns could inherit these exceptions
  without review; it must be checked against the decision table.
- `pids_limit: 512` is a conservative default and may need adjustment for a container with
  unusually high process counts.

## Related Decisions

- [2026-10-08 host hardening](2026-10-08_host-hardening.md) — history entry; the
  host-level counterpart, whose custom Lynis profile likewise documents accepted risks
  rather than chasing every suggestion.
- [2026-11-20 Grafana/Loki move to codey](2026-11-20_grafana-loki-to-codey.md) — history
  entry; the split-host layout that determines which containers are on each audit target.

## Alternatives Considered

- **Remediate every WARN.** Rejected: most findings are image defaults or deliberate
  design, and several fixes would break the services (see the exclusions above).
- **Suppress the warnings in the audit report.** Rejected: it would hide real regressions;
  the exceptions belong in a dated decision record, not in the tool output.
- **Pilot on a production service instead of `bumbleflies`.** Rejected: `bumbleflies` is
  the only statics service enabled on `servyy-test.lxd`, so it is the only service that can
  be verified first without a production deploy.
