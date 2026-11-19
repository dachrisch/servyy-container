# Landscape: one graph from domain to data, infrastructure included (2026-11-19)

The poster answered "what runs where" (server cards with chips) and "what reaches
what" in aggregate (three lanes), but not the question asked most often: *which names
does this service answer on, what does it read, what does it call?* And it drew none
of the infrastructure: Promtail, Prometheus, Watchtower, Ofelia, the LeagueSphere db
sidecars and the OpenCode gate were in the map only so `--verify` could account for
running containers.

## What changed

| | |
|---|---|
| Poster | §2 and §3 merged into **2 · Servers, domain to data**: one graph per production server (servy, codey; the card header carries role and specs — the separate host cards are gone), then cards for what a line cannot carry (each tier's servers/tenants/backup/RPO, the one door out to OpenCode and Atlas, the control plane). The aggregate "What reaches what" section is gone — the graph now draws every one of its edges. Foundation → 3, invariants → 4 |
| Graph | `domains → service → data → beyond`, one row per service **and** per infrastructure container that calls something (its role stands where domains would). Rows ordered by tier server, then project, then host, so apps and their sidecars sit together. Shared nodes: tier servers, externals, shared containers, each host's Docker engine. Calls between rows are loops. Hover traces a row |
| Map | `infrastructure:` entries take `calls: {container: [targets]}`; new target `docker:socket`. Grafana's data is its own sqlite and its Prometheus/Loki reads became `calls:`; Traefik (both), Portainer and the agent claim the socket; codey's Traefik calls the gate (forwardAuth) |
| Verifier | 18 → **47** edges. Repo: every caller's targets resolve; `docker:socket` is checked against the compose volumes **in both directions** (an undeclared socket mount is drift); a name on two hosts must be claimed by both. Live (`--verify-host`): every call — services' too, which had no live check before — needs a shared docker network other than `proxy` (proxy only counts when Traefik is one end), or the caller's env/command naming the target; tier servers by name or network; socket by mount |
| Skill | setup-home `servy-landscape`: kinds-of-edge table, the merged section, rule 4 |

The view went through three shapes on review: per registrable domain (a service with
names in three zones was drawn three times), per service group (hid Queen and League
finance sharing db-business.mongo), then one graph ordered by database, finally split
per server. The test host has no row in the map, so it gets no graph and is no longer
counted in the masthead (59 containers across 2 servers, was 76 across 3).

## Edges found (each confirmed in compose/config and on the host)

* Prometheus → pushgateway, node-exporter, cadvisor, Loki, Traefik (`prometheus.yml`)
* Promtail → Loki, socket (log discovery); cadvisor → socket (`/var/run`)
* pushgateway-bridge → pushgateway (socat)
* Grafana → Prometheus, Loki (`datasources.yml`)
* db-access / db-tunnel → leaguesphere.db (prod) and db-nonprod.mariadb (stage)
* Traefik → error-pages (both hosts); codey Traefik → opencode-authgate
* Watchtower ×3/×2, Ofelia, Portainer, the agent, both Traefiks → their host's socket

## Unclaimed edges (reverse live check)

Queen calls Firefly for intake (`FIREFLY_URL=http://finance.firefly:8080`, shared
`finance_backend`), but the map did not say so and nothing noticed: calls were only
checked claim → evidence. `verify_live_unclaimed()` adds evidence → claim: any env
value that is a URL or bare host resolving to another running container must be
covered by a `calls:` or `data:` edge. Its first run found one more real edge:
**League finance API reads `leaguesphere.db`** (`LS_DB_*` in its env template, on
`leaguesphere_database`) — a business-tier app reading the high tier. Both are in
the map now (49 edges). Negative test: removing Queen → Firefly reports exactly that
drift, naming the variable only.

Repo-side the same check is not possible for Queen: its env is rendered from secrets,
so the template text does not name Firefly. The live check is the one that counts.

While investigating, `FIREFLY_PAT` was printed in full into a session transcript (a
name-pattern redaction missed `*_PAT`). Not sent anywhere external; rotation is the
owner's call. The skill now says: print env names, not values.

## Verification

```bash
PY=/home/cda/.pyenv/versions/servy-ansible/bin/python3
$PY architecture/render.py --verify --verify-host servy.lehel.xyz --verify-host codey.lehel.xyz
# ok: 28 services, 49 dependency edges, 4 tiers agree with the repository
$PY architecture/render.py --selftest   # ok
```

Negative tests, each reporting exactly the drift it should: an unclaimed socket mount
(Traefik, caught only after the two-hosts rule — codey's claim had masked servy's),
a false socket claim (Loki), a dangling target, a sidecar pointed at the wrong tier,
and a call between containers that share only `proxy` (caught only after `proxy` was
excluded — before, it passed).

Checked in Chrome at 1440 px and at phone width (graph scrolls inside its card, notes
collapse to one column, no page-level horizontal scroll). flake8: 2 old warnings, one
fewer than before.

## Not done

* A line can pass behind a box in the data column; hover isolates a row.
* The network check is weak inside one compose project (all its containers share a
  backend network), so a wrong call between two monitor containers would pass. The
  config files (`prometheus.yml`, `promtail.yml`) are the stronger evidence, not
  parsed yet.
* The DocStash page (`app.docstash.ai/9u3hgi`) still needs its new version published.
