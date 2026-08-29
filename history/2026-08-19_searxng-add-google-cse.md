# 2026-08-19 — SearXNG: add google cse engine

## Problem
The dontforget automation chain relies on `search.lehel.xyz` for event-date extraction.
From the server's datacenter IP (49.13.6.173), Google/DDG/Qwant/Startpage are
CAPTCHA-walled or JS-gated, and Bing intermittently serves decoy/SEO-spam garbage
for niche queries like "Mindener messe" (different garbage per request). When only
Bing responds, dontforget stores no events for such queries.

## Investigation
Compared against github.com/privau/searxng (whose public instances have no such
problem). Findings:
- Our instance already runs the same engine code (vojkovic/searxng fork,
  `2026.8.4+c63835bd2`); `bing.py`/`brave.py`/`duckduckgo.py`/`google.py` are
  byte-identical to privau's.
- The real differences are operational: privau routes engine requests through
  rotating proxies (`PROXY` env → `outgoing.proxies.all://`), drops Bing/Brave/
  DDG-web from the web category in favor of google + google cse, and shortens
  suspension timeouts (CAPTCHA 60s vs our 3600s, AccessDenied 60s vs 180s).
- Verified directly from the server IP: Google `wml/search`+Nokia UA → HTTP 403;
  Google desktop `/search` → JS-gated page with zero results; **Google CSE element
  API (`cse.google.com/cse/element/v1`, JSONP) → HTTP 200 with real results**.

## Changes
1. **Added `google cse` to `keep_only`** in
   `ansible/plays/templates/searxng/settings.yml.j2` so it is picked up from the
   default engine set.
2. **Enabled + tokenized it**: `disabled: false` (ships disabled by default in the
   upstream defaults) and reuses the existing shared token
   (`vault_searxng_google_token`), so the dontforget API token can reach it.
   - The current SearXNG `google cse` engine needs **no API key** — it uses
     Google's public CSE (`partner-pub-8993703457585266:4862972284`) and fetches a
     `cse_token` from `cse.google.com/cse/cse.js`, then queries the JSONP element
     endpoint. No `secrets.yml` change required.
3. No proxy / suspension-timeout changes in this commit (documented as durable
   follow-up — see issue context).

## Deploy
```
cd ansible && ansible-playbook servyy.yml -i production --tags user.docker.searxng \
  --limit lehel.xyz -e ansible_user=cda
```

## Verification
- `docker ps` → `searxng.core` + `searxng.valkey` Up
- `settings.yml` on server contains `google cse` in `keep_only` + engine block
- API queries return real results (engines now include `google cse`):
  - `q=Mindener messe` → 15 google cse + 10 bing (Wikipedia, minden.de, mt.de,
    minden-erleben.de, Instagram, …)
  - `q=Mindener messe careers` → 20 google cse + 10 bing (incl. Berufswelt Minden
    job postings)
  - `q=Leipziger Buchmesse` → 18 google cse + 3 qwant + bing
  - `q=Messe Berlin 2026` → 16 google cse + bing
- No new errors in `docker logs searxng.core`

## Files changed
- `ansible/plays/templates/searxng/settings.yml.j2`
- `history/2026-08-19_searxng-add-google-cse.md`

## Follow-up (durable fix, not done here)
- Route outbound engine requests through a rotating proxy (`outgoing.proxies.all://`)
  so Google/DDG/Qwant/Startpage/Brave stop CAPTCHA-ing/JS-gating the datacenter IP.
- Shorten suspension timeouts (`SearxEngineCaptcha` 3600s → 60s,
  `SearxEngineAccessDenied` 180s → 60s) so transient blocks recover quickly.