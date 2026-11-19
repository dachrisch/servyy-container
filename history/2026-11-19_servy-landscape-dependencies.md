# Landscape: dependency edges, and the skill that reads them (2026-11-19)

The map said what runs where. It could not answer *what depends on what*: an app's
database was written down but never drawn, nothing named the OpenCode server, and the
container that sits on that path was in no section at all. This closes that gap with
one new section, one schema, and — because the poster shows aggregates — a verifier
that carries the proof.

## What changed

| | |
|---|---|
| Skill | `servyy-architecture` → **`servy-landscape`** (setup-home `agent-config/skills`), because it now answers "what depends on what", not only "what runs where" |
| Server copy | `roles/opencode/defaults/main.yml`: new name in `opencode_server_shared_skills`, old name in `opencode_server_retired_skills` (the copy tasks do not prune) |
| Map schema | `externals:` (the two places apps leave the building), per-service `calls:`, `data.tenant:`, `control:`, `host:` on every `infrastructure:` entry |
| Renderer | section **3 · What reaches what** — three lanes: inward to the tiers, outward to codey/opencode, and the control plane. Masthead gains `dependency edges` and `apps → codey` |
| Verifier | `verify_edges()` (repository) and `verify_live_edges()` (env + docker networks on the host); `--verify` now reports **28 services, 18 dependency edges** |

An edge is written once: a database is its service's `data:` block (never repeated in
`calls:`), a call is a `calls:` target, and an outward dependency is an `externals:`
row plus the `calls:` reference. `db:` is the database the app actually uses;
`tenant:` is the inventory key the checker matches on — the two are not the same
string and conflating them is how the old map got LeagueSphere wrong.

## Findings (each one real, each one fixed here)

* **`leaguesphere-prod` had the wrong database.** The map said `db: leaguesphere`;
  the inventory and the running stack say `web35_db8`, owned by `web35_8`. The
  public demo was wrong the same way (`leaguesphere_demo` vs `demo_db`/`demo_user`).
* **`firefly-importer` is an app→app edge, not an app→database edge.** It calls
  `FIREFLY_III_URL=http://firefly:8080`; nothing on that container talks to the
  private tier. Recorded as a data edge it claimed a connection that does not exist.
* **`opencode-authgate` was unmapped.** It runs on codey, and it is the only thing
  standing between the API key and `opencode.web`. Added as codey infrastructure; the
  three apps that cross it are `dontforget`, `groceries` and `finance.queen` (their
  env carries `OPENCODE_BASE_URL=https://code.lehel.xyz`).
* **`dontforget.bumbleflies.de` answered 502.** DNS points it at servy, but the
  running container has no `-bf` router (`BUMBLEFLIES_HOST` unrendered), so the map
  no longer claims the domain. It rejoins the list when a deploy serves it.
* **`job-search` was missing from `ignore_projects`** while carrying an
  `OPENCODE_BASE_URL` template and no deployment — exactly the shape that would have
  been reported as an unlisted outward edge. It is now named, with devhub.

## What the verifier actually checks

| Edge | Repository | Host (`--verify-host`) |
|---|---|---|
| data | tenant row exists, same server, same tier, same `db`; same `user` for MariaDB | the server is named in the container env **or** the container sits on the tier's network |
| call | the target resolves to a service, a container, a tier server or an `external:` | — |
| external | the project's compose file or env template names the external's `check:` key or `via:` host — **in both directions** | the env on the container carries that key |

Queen is why both live signals are needed: no env on `finance.queen` names
`db-business.mongo`, only its `db_business_backend` membership does.

Negative tests run before publishing (each reports exactly one drift): an edge with
no evidence, evidence with no edge, a renamed database, a dangling target, a tenant
moved to another server, a live container whose env denies the claimed edge, and a
live container moved to another tier.

## Deliberately not done

* That `dontforget`'s inventory `user` is `dontforget` while the live and secret
  value is `dontforget_app`. Mongo accounts are not asserted by `roles/db_tier`, so
  comparing them would answer a question this check cannot ask; the map keeps the
  live username and the comparison is MariaDB-only. Worth its own five-minute fix in
  `db_tenants.yml`.
* No per-service arrow on the poster: 28 arrows is a hairball. The page shows counts
  and lanes, `--verify` holds the per-edge truth, and the skill says so out loud.

Design and traps: `architecture/landscape.yaml`. Workflow: the `servy-landscape`
skill. Poster: new version of `app.docstash.ai/9u3hgi`.
