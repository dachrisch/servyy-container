# LeagueSphere Scorecard 404 — "Could not create team logs ... team {X} not found"

**Date:** 2026-06-22
**Service:** `leaguesphere.app` (production, `leaguesphere.app` domain)
**Type:** Root-cause investigation (application bug, not infrastructure)
**Status:** Root cause identified — fix belongs in the LeagueSphere app repo, not this infra repo

---

## Problem

During live game-day scoring, users hit an error when saving the **first** scorecard
entry of a game:

```json
{"detail":"Could not create team logs ... team Paderborn Dolphins not found"}
```

Reported via screenshot (phone clock 11:40 CEST = 09:40 UTC, game *Bielefeld vs Paderborn*,
status `1. Halbzeit 0:0`, first entry `#42`).

### Symptom characteristics
- `POST /api/gamelog/{id}` returns **HTTP 404** with the above body.
- The error is **not logged server-side** — DRF returns it only in the 404 response body,
  so it appears **only in the nginx access log** (`leaguesphere.www`), never as a backend
  `ERROR`. Log-level dashboards in Grafana/Loki do not catch it.
- **Intermittent**: only the *first* entry right after the coin toss fails. Retries /
  subsequent entries succeed (201).

### Observed in Loki (2026-06-21)
Examples of failing first-entry POSTs (status 404), each followed by later 201s for the
same game once possession flipped:

| Time (CEST) | Request | Status | Home / Away (DB short names) |
|---|---|---|---|
| 11:30 | POST /api/gamelog/7794 | 404 | Regen2 / Rosen |
| 11:34 | POST /api/gamelog/7666 | 404 | SGRostockLüb / Lions2DFFLF |
| 11:34 | POST /api/gamelog/8942 | 404 | Erlangen2 / Ingol |
| (screenshot) | POST /api/gamelog/7973 | 404 | Biele / **Paderborn** |

---

## Root Cause

A **name-vs-description mismatch between the read/display path and the write path.**

Each `Team` has two name fields:

```
Team.name          short, unique   e.g. 'Paderborn'           (write path uses this)
Team.description    full club name  e.g. 'Paderborn Dolphins'  (display path uses this)
```

Confirmed in DB:
```
id=400  name='Paderborn'  description='Paderborn Dolphins'
id=95   name='Biele'      description='Bielefeld Bulldogs'
```

### Write path resolves by `name`
`gamedays/service/game_service.py:30`
```python
def create_gamelog(self, team_name, event, user, half):
    team = Team.objects.get(name=team_name)   # SHORT name only
```
Caught in `gamedays/api/game_views.py:104-106` → raises `NotFound` (404) on
`Team.DoesNotExist`.

### Display path emits `description`
`/api/gameday/{id}/officials/{team}` → `gamedays/service/gameday_service.py:377/386`
```python
self.home_team_name = home_row["team__description"]   # 'Bielefeld Bulldogs'
self.away_team_name = away_row["team__description"]    # 'Paderborn Dolphins'
```

### The leak: the `?start=` URL param
The full description leaks from the display layer into a POST exactly once per game:

1. Coin-toss screen `scorecard/src/components/scorecard/Officials.jsx` gets the game from
   `GET /api/gameday/{id}/officials/{team}` → `selectedGame.home/away` = **description**.
2. Possession radios use `selectedGame.home/away` (`Officials.jsx:270-280`) →
   `fhPossession = "Paderborn Dolphins"`.
3. "Spiel starten" navigates to `…/details?start=Paderborn Dolphins` (`Officials.jsx:178`).
4. `Details.jsx:24` reads the URL param → `setTeamInPossession("Paderborn Dolphins")`.
5. First "Eintrag speichern" posts it verbatim (`Details.jsx:74`):
   `{team: "Paderborn Dolphins", ...}`.
6. Backend `Team.objects.get(name="Paderborn Dolphins")` → `DoesNotExist` → **404**.

### Why retries succeed
The scorecard buttons and every *subsequent* entry use `gameLog.home.name /
gameLog.away.name`, which come from `GET /api/gamelog/{id}` — that endpoint annotates
home/away from the **short `name`** (`game_views.py:40-47`, `team_column="name"`).
Once possession flips off the `?start=` value, all saves resolve correctly.

### Inconsistency already present in the codebase
- `game_service.py:30` → `Team.objects.get(name=...)`
- `schedule_resolution_service.py:68` → `Team.objects.get(description=...)`

The two lookup conventions coexist; the `?start=` param is the one place a `description`
reaches a `name`-based lookup.

---

## Data flow (summary)

```
/api/gameday/{id}/officials/{team}   --> selectedGame.home/away  = description  ("Paderborn Dolphins")
        │ (coin toss)
        ▼
Officials.jsx  fhPossession = selectedGame.away
        │  Navigate ?start=Paderborn Dolphins
        ▼
Details.jsx  teamInPossession = start  --> FIRST POST /api/gamelog {team: "Paderborn Dolphins"}
        ▼
game_service.create_gamelog -> Team.objects.get(name="Paderborn Dolphins")  -> DoesNotExist -> 404

(every later entry uses gameLog.*.name = "Paderborn" -> 201 OK)
```

---

## Recommended Fix (in the LeagueSphere app repo — NOT this infra repo)

In priority order:

1. **Tolerant backend lookup** (one line, stops the bleeding for live game days)
   — `game_service.py:create_gamelog`:
   ```python
   from django.db.models import Q
   team = Team.objects.get(Q(name=team_name) | Q(description=team_name))
   ```
2. **Proper long-term fix:** pass `team_id` through `?start=` and the gamelog POST instead
   of a name string; look up by id. Eliminates the name/description ambiguity entirely.
3. **Alternative:** make `/api/gameday/{id}/officials/{team}` expose the short `name`
   (like `/api/gamelog` does) so `selectedGame.home/away` matches the write path — but the
   coin-toss screen loses the nicer full-name display.

Recommendation: **#1 now + #2 as follow-up.** Add a regression test that posts a first
gamelog entry using the team description and asserts 201.

---

## Verification commands

```bash
# Container / status (was restarted ~3h before investigation, morning docker logs gone)
ssh lehel.xyz "docker ps --filter name=leaguesphere.app --format '{{.Names}} {{.Status}}'"

# Find failing first-entry POSTs in nginx access log via Loki (status 404 on POST gamelog)
LOKI_URL="https://monitor.lehel.xyz/loki"; TENANT="servyy-logs-k8x9m2p4q7"
curl -s -H "X-Scope-OrgID: $TENANT" "$LOKI_URL/api/v1/query_range" \
  --data-urlencode 'query={job="docker",container="leaguesphere.www"} |~ "POST /api/gamelog" |~ " 404 "' \
  --data-urlencode "start=$(date -u -d '2026-06-21 00:00' +%s)000000000" \
  --data-urlencode "end=$(date -u -d '2026-06-21 22:00' +%s)000000000" --data-urlencode "limit=200" \
  | jq -r '.data.result[]?.values[]? | .[1]'

# Confirm name vs description for an affected team (read-only ORM inside container)
ssh lehel.xyz "docker exec leaguesphere.app python manage.py shell -c '
from gamedays.models import Team
t = Team.objects.get(pk=400)
print(repr(t.name), repr(t.description))'"
```

---

## Related / Notes

- Separate, larger issue observed the same day (logged backend errors): `Cannot generate
  events table … event teams don't match expected` / `Events data mismatch` — placeholder
  teams (`P1 Gruppe 2`, `Verlierer HF 1`) or single-team event sets. Tracked separately;
  see prior investigation `history/` / memory `leaguesphere_performance_investigation_20260530`.
- Infrastructure is healthy: container `Up (healthy)`, Traefik routing fine. All findings
  are application-level bugs in LeagueSphere.
