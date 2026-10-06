# 2026-10-06 queen prod enablement + Traefik fixes (test + prod)

Queen (`bumbleflies/queen`, image `bumblecode/queen:latest`) went live on prod
at `https://queen.bumbleflies.de` (healthy, valid LE cert, OAuth-ready).
PRs #169 (reconcile path + env), #172 (GLS/Drive secrets + prod gate),
#173 (QUEEN_SERVICE_HOST interpolation), #174 (HTTP-01 resolver),
#175 (QUEEN_TRAEFIK_* interpolation). All CI green, test-first each step.

## What was wrong / fixed

1. **Ofelia reconcile path** (#169, already merged before this session):
   `dist/server/cron/reconcile.js` → `dist/src/server/cron/reconcile.js`
   (tsconfig `rootDir: "."` emits under `dist/src/`). Reason it slipped through:
   labels are opaque strings, job fires 07:30 only, test never exec'd the path.
2. **Traefik `Host(``)`** (#173): `QUEEN_SERVICE_HOST` lived only in `queen.env`
   (container runtime), invisible to compose interpolation. Added to
   `finance/docker.env.j2` (.env) + `:-` default in compose label.
3. **DNS-01 impossible for bumbleflies.de** (#174): Porkbun API scope covers
   lehel.xyz only (`INVALID_DOMAIN`). Prod queen uses `letsencrypthttpresolver`
   (HTTP-01), same as `bumbleflies_prod` / `leagues-finance`. A record already
   pointed at servy — no Porkbun entry needed for simple subdomains.
4. **TRAEFIK_* same interpolation bug** (#175): `queen.env` values never reach
   compose labels. Added `QUEEN_TRAEFIK_ENTRYPOINT/TLS/CERTRESOLVER` to
   `docker.env.j2`, labels use them. Lesson: anything a compose label
   interpolates MUST be in `.env`, never only in a service-specific env file.

## Secrets resolved live

- `queen.gls_account_id: "1"` — prod Firefly asset #1 = bumbleflies UG
  (business GLS; #2 = Christian Dähn personal). Both via Enable Banking.
- `queen.drive_invoices_folder_id: "1wm9ifWTLwSYNESR2FrFi3fG-42GQsulE"`
- `admin_emails: christian.daehn`, `bank_start: 2025-01-01` confirmed.

## Verification (prod servy.lehel.xyz)

- `finance.queen` healthy, `/health` → ok (internal + public 200, TLS 1.3)
- env: ADMIN_EMAILS / GLS=1 / BANK_START / DRIVE_ID / CLIENT_URL correct
- Router `Host(queen.bumbleflies.de)` + httpresolver, cert issued
- `portainer.ofelia`: `daily-reconcile` registered (restart needed after each
  queen recreate — Ofelia misses label changes in its boot window, known quirk)

## Known gaps / follow-ups

- **`:latest` image (rev 5311f78) has NO `dist/src/server/cron/reconcile.js`**
  (queen repo still planning, only index/health/app/mongo). Daily 07:30 job
  will fail loudly until queen ships it. Path is at least correct now.
- Mongoose warning in queen log: duplicate index on `fireflyJournalId`
  (upstream queen issue, cosmetic).
- `ansible/plays/roles/user/defaults/main.yaml` shows git-crypt drift
  (empty worktree vs 22-byte blob, no .gitattributes entry) — pre-existing,
  untouched, out of scope.
- Google OAuth: reused leagues.finance client — needs
  `https://queen.bumbleflies.de/auth/google/callback` in authorized redirects
  before login works. Drive "Senden & ablegen" untested end-to-end.
