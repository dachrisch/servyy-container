# Regression: a global `Referrer-Policy: no-referrer` broke every Django login

**Date:** 2026-10-30
**Status:** ✅ Diagnosed; fix in `traefik/dynamic.yaml` (referrerPolicy removed)
**Relates to:** `2026-10-29_traefik-security-headers.md` (the change that caused it),
`2026-10-29_traefik-3.7-upgrade.md`

## Symptom

After the security-header rollout (2026-10-30 00:18), LeagueSphere stopped accepting logins.
`stage.leaguesphere.app/login/?next=/home/` answered

> **Verboten (403)** — CSRF-Verifizierung fehlgeschlagen. Anfrage abgebrochen.

## Root cause

`security-headers@file` set `referrerPolicy: "no-referrer"` on the `websecure`/`web` entrypoints.
When a page is served with `no-referrer`, the browser sends **no `Referer` header** on the
subsequent form POST — and Chrome additionally serialises **`Origin: null`** for that navigation
request. Django's CSRF check needs one of the two:

* missing `Referer` → `Referer checking failed - no Referer.`
* `Origin: null` → `Origin checking failed - null does not match any trusted origins.`

Both were observed in production. The two apps then differed only by Django version/flow:

| app | log line | when |
|---|---|---|
| `leaguesphere.app` (prod) | `Referer checking failed - no Referer.` ×3 | 00:22:10, 00:48:06, 00:48:07 — i.e. 4 min after the 00:18:13 recreate |
| `leaguesphere_stage.staging-app` | `Origin checking failed - null …` ×2 | 07:38:44, 07:38:58 |

`leaguesphere-demo` had no failures only because nobody logged in during the window (0 hits).

### Reproduction (headless Chrome, 07:41)

`POST https://stage.leaguesphere.app/login/?next=/home/` → **403**, with request headers

```
origin: null
cookie: csrftoken=…
sec-fetch-site: same-origin
(no referer at all)
```

The token itself was valid — the request was rejected on origin/referer alone.

### Why the app's own healthcheck did not catch it

`leaguesphere_stage.www` logs a POST every ~10 s from the container healthcheck, and it returns
**200** the whole time — because that healthcheck sends `Referer: https://stage.leaguesphere.app/login/`
explicitly. It exercises CSRF token handling, not browser referrer behaviour, so it passed while
real browsers failed.

## Why the original reasoning missed it

The rollout set only headers that were "equal-or-stronger than what the backends send", and
`no-referrer` is strictly stronger than the `strict-origin-when-cross-origin` that
`leaguesphere/league_manager/settings/{prod,stage}.py` declare via `SECURE_REFERRER_POLICY`.
*Stronger is not the same as safe*: the Django apps depend on the referer being present, so the
"upgrade" removed an input to application logic. The same weakness applies to any header an app
consumes rather than merely declares.

## Fix

`referrerPolicy` is removed from `security-headers` rather than relaxed to another global value.
Traefik's entrypoint middleware always overwrites the backend's own header, so **any** global
choice overrides every app; the correct behaviour is the one the apps declare themselves, which is
what happens when the key is absent:

| host | policy in effect after the fix |
|---|---|
| leaguesphere prod + stage | `strict-origin-when-cross-origin` (their `SECURE_REFERRER_POLICY`) |
| leaguesphere demo | `same-origin` (Django's default) |
| energy, search, finance | `no-referrer` (they set it themselves; unaffected) |
| everything else | browser default, `strict-origin-when-cross-origin` |

`HSTS`, `X-Content-Type-Options`, `X-Frame-Options: DENY` and the `Server`/`X-Powered-By` removal
stay: none of them is consumed by an application's request logic.

## Portfolio sweep (30 public hosts, 2026-10-30 ~08:00)

Checks run to confirm the blast radius was LeagueSphere only:

| check | result |
|---|---|
| `grep -ciE 'checking failed\|csrf\|origin checking\|referer checking'` over **every** container's last 12 h of logs, both hosts | only `leaguesphere.app` (3), `leaguesphere_stage.staging-app` (3, one of them the probe). The `.www` frontends match only because their healthcheck user-agent/Referer contains "csrf" — all 200s |
| HTTP status of all 30 public hostnames | all as designed (200/301/302/303/307); no 5xx |
| `<iframe>` in any served HTML | **none** — so `X-Frame-Options: DENY` cannot break an embedding page anywhere in the fleet |
| `m.leaguesphere.app` (Moodle, was `SAMEORIGIN`, now `DENY`) | `/` 200, 85 KB, login form renders |
| SPAs boot: portainer, photoprism, pass, monitor (Grafana 13.3), git, search, energy, groceries, dontforget, ibs | all render their login/view (`document.title` + DOM content verified in a real browser) |
| apps with their own CSP / Permissions-Policy (photoprism, portainer, pass, firefly) | still exactly one CSP each, their own Permissions-Policy — untouched |
| `firefly` duplicate `X-Frame-Options`/`X-Content-Type-Options`/`Referrer-Policy` pairs | collapsed to one each (the intended testssl MEDIUM fix) |

Vaultwarden, Gitea, Grafana, Moodle, Firefly (Laravel), SearXNG (Flask) and the Go apps do not
validate `Referer`/`Origin` on their form posts, so `no-referrer` never affected them.

## Consequences

### Positive

- The failing input is gone; Django CSRF works again with each app's declared policy
- The middleware now documents the *functional compatibility* condition, not just "stricter is better"
- The portfolio sweep is on record, so the next header change has a baseline

### Negative / Tradeoffs

- Hosts without their own policy no longer advertise a `Referrer-Policy` header (behaviour is
  identical — the browser default is `strict-origin-when-cross-origin`) — humble will count one more
  "missing header" on those hosts
- Anything we might want to harden later must be set per app, not centrally

## Verification after deploy

```bash
# stage + prod: header must be the app's own, and a browser login must work
curl -sI https://stage.leaguesphere.app/login/ | grep -i referrer-policy   # strict-origin-when-cross-origin
curl -sI https://energy.lehel.xyz/          | grep -i referrer-policy      # no-referrer (app's own)
ssh servy.lehel.xyz "docker logs --since 10m leaguesphere.app | grep -c 'checking failed'"   # 0
```
