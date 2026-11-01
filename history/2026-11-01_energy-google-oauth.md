# Energy Service: Google OAuth Credentials (Gmail/Drive Intake)

**Date:** 2026-11-01
**Status:** ✅ Completed (infra side) — app code pending in dachrisch/energy.consumption#720
**PR:** #261 (merged to master)

## Summary

The energy app gains a Google provider intake (Gmail → Drive → consolidate). It needs a Google OAuth web client. The credentials are now stored in the encrypted secrets file and rendered into `energy.env` on production.

## Google Cloud Setup

- **Project:** `gen-lang-client-0729324370` ("Gemini API", already used for the energy OCR key)
- **Google Auth Platform:** app "Energy Monitor", user type External, publishing status **Testing**
  - Test user: christian.daehn@gmail.com (100-user cap while unverified)
  - Scopes: `gmail.readonly` (restricted) and `drive.file` (non-sensitive)
- **APIs enabled:** Gmail API, Google Drive API
- **OAuth client:** "Energy Monitor Intake" (Web application)
  - JS origins: `http://localhost:3000`, `https://energy.lehel.xyz`
  - Redirect URIs: `http://localhost:3000/api/google/callback`, `https://energy.lehel.xyz/api/google/callback`

## Files Changed

- `ansible/plays/vars/secrets.yml` (git-crypt): `energy.google_client_id`, `energy.google_client_secret`
- `ansible/plays/roles/docker_service/templates/energy/.env.j2`:
  ```
  GOOGLE_CLIENT_ID={{ energy.google_client_id }}
  GOOGLE_CLIENT_SECRET={{ energy.google_client_secret }}
  GOOGLE_CALLBACK_URL=https://{{ service_host }}/api/google/callback
  ```

## Deployment

The `testing` inventory does not enable energy, so a servyy-test run would skip it. Its `mongodb_uri` is probably the production database, so enabling it on test was not an option. Instead, the agreed test step was:

1. Rendered the template locally with `secrets.yml` and `service_host=energy.lehel.xyz`. Output was correct.
2. Production dry-run: `./servyy.sh --limit servy.lehel.xyz --tags user.docker.energy --check` showed changed=2 (energy.env plus the redeploy) and failed=0.
3. Deployed: `./servyy.sh --limit servy.lehel.xyz --tags user.docker.energy` gave changed=2, failed=0.

## Verification

```bash
ssh servy.lehel.xyz 'docker ps --filter name=energy --format "{{.Names}} {{.Status}}"'
ssh servy.lehel.xyz 'docker exec energy.energy printenv | grep ^GOOGLE_ | sed -E "s/(SECRET=).*/\1***/"'
curl -s -o /dev/null -w "%{http_code}\n" https://energy.lehel.xyz/   # 200
```

Result: `energy.energy` is healthy, all three `GOOGLE_*` vars are present, and the callback is `https://energy.lehel.xyz/api/google/callback`.

## Known Issues / Follow-ups

- The variables are unused until dachrisch/energy.consumption#720 is merged and released.
- The app stays in Testing mode, so users see an "unverified app" warning. Public use of `gmail.readonly` needs OAuth verification (CASA).
- **Secret rotation:** create a new secret in the Cloud Console (Clients → Energy Monitor Intake), update `secrets.yml`, then redeploy with `--tags user.docker.energy`.
