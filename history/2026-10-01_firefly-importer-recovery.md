# 2026-09-30/10-01 Firefly III Automated Import Recovery

**Date:** 2026-09-30 → 2026-10-01
**Status:** Completed, verified over two mornings
**Environment:** servy.lehel.xyz (production)
**Commit:** `ec3a96e` — "fix: restore Firefly III automated imports with fresh credentials"

## Problem

The Firefly III Data Importer (`finance.importer`, Ofelia `daily-import` job) ran but imported
nothing. Every scheduled run returned HTTP 500 from `/autoupload`, masked as success
(Ofelia `failed: false`) because `run-import.sh` used plain `curl` without `--fail`.

## Root causes found (4 stacked failures)

1. **Dead Firefly PAT** — `finance.firefly_pam_token` in `secrets.yml` rejected by Firefly
   (`401 Unauthenticated` on `/api/v1/about`). Firefly UI showed zero personal access tokens.
2. **Enable Banking private key was git-crypt ciphertext** — `finance/import/eb.pem` in this
   checkout (and on the server, and in backups) was the encrypted blob, not a PEM.
   Importer: `OpenSSL unable to validate key`. No plaintext copy existed anywhere reachable.
3. **Stale Enable Banking session/account IDs** — April `banking_session`/`banking_auth_id`
   belonged to the deleted app (`404 SESSION_DOES_NOT_EXIST`); the EB account UID in config
   likewise (`404 ACCOUNT_DOES_NOT_EXIST`).
4. **Empty Firefly + no auto-create** — Firefly had 0 accounts and the template rendered
   `"new_accounts": []`, so nothing could be mapped. Also `accounts: {}` meant
   "0 accounts to download from" (unmapped accounts must be present with ID `0`).

Latent bugs fixed along the way:

- **Hourly misfires:** Ofelia parses 5-field specs seconds-first, so `0 6 * * *` ran every
  hour at :06. Proof: sibling job `demo-reset` with 6-field `0 0 0 * * *` runs once daily
  at midnight. Changed to `0 0 6 * * *` (+ Ofelia restart to re-register).
- **Ansible double-encoded the EB key:** `slurp` returns base64-of-file; the template stripped
  PEM armor from the still-encoded string (no-op), so the importer received base64-of-PEM
  instead of the bare key body. Added `b64decode` first in `user.yml`.
- **Silent curl:** added `--fail` to `run-import.sh.j2` (with `set -e`, HTTP ≥400 now fails
  the Ofelia job visibly).

## Solution

1. Created Firefly PAT `importer-2026-09-30` (Profile → Remote access and tokens), deployed
   via `secrets.yml`.
2. Registered new Enable Banking PRODUCTION app `46bc4233-b708-4a17-8811-1aa857e17bf4`
   (old `7bb05ea7…` removed) with a fresh RSA-2048 keypair; redirect
   `https://finance-importer.lehel.xyz/eb-callback` (confirmed from importer route
   `eb-connect.callback`).
3. Drove bank consent via EB API directly (`POST /auth` + user consent at GLS +
   exchanged `code` via `POST /sessions`), bypassing the importer UI.
4. New session `1a486b13-2bcf-4e52-b6f1-a16ff3336252` (consent valid until 2026-12-28)
   into `import_config`; template rebuilt with `new_accounts` auto-create for both GLS
   accounts (UIDs `8898962a…`, `b3649be5…`).
5. Deployed (`user.docker.repo,user.docker.env,user.docker.finance`), verified live.

## Files changed (commit ec3a96e)

- `ansible/plays/vars/secrets.yml` — new PAT, new `enable_banking_app_id`, new
  `banking_auth_id`/`banking_session`; dropped stale `account_uuid`/`account_id`
- `finance/import/eb.pem` — fresh RSA private key (git-crypt encrypted at rest)
- `ansible/plays/roles/user/templates/finance-import-config.json.j2` — `accounts`
  `{uid: 0}` + `new_accounts` auto-create for both accounts
- `ansible/plays/roles/user/templates/run-import.sh.j2` — `curl --fail`
- `ansible/plays/user.yml` — `b64decode` before PEM-armor strip
- `finance/docker-compose.yml` — Ofelia schedule `0 0 6 * * *`

## Verification

```bash
# Manual import returns 200 (was 500 every run)
ssh servy.lehel.xyz "docker exec finance.importer /bin/bash -c /import/run-import.sh"
# Importer logs show accounts created + transactions downloaded:
ssh servy.lehel.xyz "docker logs finance.importer --since 30m 2>&1 | grep -a -E 'Newly created account|TransactionsResponse: count|POST.*autoupload'"
# Firefly transaction count (PAT in secrets.yml):
curl -H "Authorization: Bearer $PAT" "https://finance.lehel.xyz/api/v1/transactions?limit=1"
# Next-morning check (2026-10-01 06:00 UTC run):
ssh servy.lehel.xyz "docker logs portainer.ofelia --since 24h 2>&1 | grep -a daily-import"
```

**Results:** first full run created Firefly accounts #1/#2, downloaded 25 + 239
transactions (`POST → 200`); Firefly total 0 → 264. Morning-after run (Oct 1, 06:00,
single run, 2m02s, `failed: false`): 25 + 242 fetched, total 264 → 287 (+23 new,
rest correctly rejected as `a117` duplicates).

## Known issues / follow-ups

- **Firefly 6.7.6 breaks `/oauth/authorize`** (`jc5/google2fa-laravel` Middleware calls
  `withCookie()` on a Symfony response → 500). Importer-UI login via Firefly OAuth is
  broken; worked around via direct EB API. Consider reporting upstream.
- **Same hourly-cron bug class on codey:** `prune-sessions` (`0 4 * * *`) and
  `hub-force-cleanup` likely misfire hourly — same 6-field fix applies.
- **EB consent expires** (current: 2026-12-28) and sessions die with app rotation; expect
  to repeat the consent + session refresh in ~90 days.
- Ofelia does not always re-read labels on container recreate (observed 22:06 stale run);
  restart `portainer.ofelia` after label changes.

## Rollback

Previous app/PAT/session values are in git history (`git show HEAD~1:...`). To disable:
remove the `ofelia.*` labels from `finance/docker-compose.yml` and redeploy.

## Runbook: refreshing an expired Enable Banking session

Do this when the daily import starts failing with EB errors (`SESSION_DOES_NOT_EXIST`,
consent-expired, or 401s from `api.enablebanking.com` in `docker logs finance.importer`).
Current consent for session `1a486b13…` is valid until **2026-12-28**. Takes ~10 min, most
of it waiting on the bank login. Endpoints are singular (`/auth`, `/sessions`) — NOT
`/auths`.

Prerequisites: repo checked out with git-crypt unlocked; `ENABLE_BANKING_APP_ID` from
`ansible/plays/vars/secrets.yml`.

1. **Mint a 1h app JWT** (private key never leaves the server — this uses the deployed
   `ENABLE_BANKING_PRIVATE_KEY` inside the importer container, which bundles
   `firebase/php-jwt`):
   ```bash
   cat > /tmp/eb-jwt.php <<'EOF'
   <?php
   require '/var/www/html/vendor/autoload.php';
   $body = getenv('ENABLE_BANKING_PRIVATE_KEY');
   $key = "-----BEGIN PRIVATE KEY-----\n" . implode("\n", str_split($body, 64)) . "\n-----END PRIVATE KEY-----\n";
   $now = time();
   $payload = ['iss' => 'enablebanking.com', 'aud' => 'api.enablebanking.com', 'iat' => $now, 'exp' => $now + 3600];
   echo Firebase\JWT\JWT::encode($payload, $key, 'RS256', getenv('ENABLE_BANKING_APP_ID'));
   EOF
   ssh servy.lehel.xyz "docker exec -i finance.importer php" < /tmp/eb-jwt.php > /tmp/eb-jwt.txt
   ```
2. **Start the bank authorization** (valid 89 days, same redirect the importer expects):
   ```bash
   JWT=$(cat /tmp/eb-jwt.txt); VALID_UNTIL=$(date -d "+89 days" +%Y-%m-%dT%H:%M:%S%:z)
   curl -s -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
     -d "{\"access\":{\"valid_until\":\"$VALID_UNTIL\"},\"aspsp\":{\"name\":\"GLS Gemeinschaftsbank\",\"country\":\"DE\"},\"state\":\"manual-$(date +%Y%m%d)\",\"redirect_url\":\"https://finance-importer.lehel.xyz/eb-callback\",\"psu_type\":\"personal\"}" \
     https://api.enablebanking.com/auth
   ```
   Save the returned `authorization_id` and open the returned `url`.
3. **User completes GLS login + consent** in the browser. The redirect lands on the
   importer's `/eb-callback`, which shows an error page ("no import job") — expected,
   harmless. Nothing else is needed from the browser.
4. **Grab the code** (single-use, expires in minutes) from the importer access log and
   **exchange it immediately**:
   ```bash
   ssh servy.lehel.xyz "docker logs finance.importer --since 10m 2>&1 | grep -a 'eb-callback' | tail -n 1"
   # → GET /eb-callback?state=...&code=<CODE>
   JWT=$(cat /tmp/eb-jwt.txt)
   curl -s -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
     -d '{"code":"<CODE>"}' https://api.enablebanking.com/sessions | head -c 600
   # → {"session_id":"<NEW>","accounts":[...]}
   ```
5. **Update `ansible/plays/vars/secrets.yml`** (`finance.import_config`): new
   `banking_auth_id` (step 2) + `banking_session` (step 4). If the response shows
   **different account UIDs** than `finance-import-config.json.j2` has, update
   `accounts`/`new_accounts` there too.
6. **Deploy + verify** (repo tag syncs compose files, env tag re-renders config):
   ```bash
   cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "user.docker.repo,user.docker.env,user.docker.finance"
   sleep 45  # let finance containers settle if recreated
   ssh servy.lehel.xyz "docker exec finance.importer /bin/bash -c /import/run-import.sh"  # expect HTTP 200
   ssh servy.lehel.xyz "docker logs finance.importer --since 10m 2>&1 | grep -a -E 'TransactionsResponse: count|Zero transactions|POST.*autoupload' | tail -n 5"
   ```
   Success = `TransactionsResponse: count N` per account, `POST /autoupload … 200`,
   Firefly `/api/v1/transactions` total grows.
7. **Clean up + commit:** `rm /tmp/eb-jwt.php /tmp/eb-jwt.txt`; commit/push the
   `secrets.yml` (+ template if touched) change.
8. If anything looks off, the Ofelia job now fails loudly (`curl --fail`), so
   `docker logs portainer.ofelia | grep daily-import` shows it next morning.
