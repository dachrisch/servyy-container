# 2026-11-20 — Pin dbaccess on for production `ls_app`

## Problem

`ls_app/templates/ls.env.j2` renders `DBACCESS_ENABLED` from
`dbeaver_dbaccess_enabled | default(false)`, so the flag had to be passed as
`-e dbeaver_dbaccess_enabled=true` on **every** `ls.app.prod` run. On 2026-11-20 a routine
prod app run for an unrelated change (enabling the Liveticker v2 flags,
leaguesphere#2496) ran without it: `ls.env` was re-rendered with `DBACCESS_ENABLED=false`,
and `leaguesphere.app` restarted at 17:57:19 UTC with the dbaccess request/approval surface
switched off in production.

## What was done

1. Restored immediately with
   `./servyy.sh --tags ls.app.prod -e dbeaver_dbaccess_enabled=true --limit servy.lehel.xyz`
   (failed=0). Verified read-only: `docker exec leaguesphere.app printenv DBACCESS_ENABLED`
   → `true`. `LIVETICKER_V2_ENABLED` and `LIVETICKER_STREAM_ENABLED` stayed `true`.
2. This change pins `dbeaver_dbaccess_enabled: true` on the two production `ls_app` entries in
   `ansible/plays/leaguesphere.yml` (jail + dev env copy). Stage and other targets keep the
   default `false` and still need the explicit `-e`.
3. The comment in `ls.env.j2` now says where production pins it.

## Files changed

- `ansible/plays/leaguesphere.yml`
- `ansible/plays/roles/ls_app/templates/ls.env.j2` (comment only)

## Verification

After merge, a plain prod app run must keep dbaccess on:

```bash
cd ansible
./servyy.sh --tags ls.app.prod --limit servy.lehel.xyz
ssh servy.lehel.xyz 'sudo docker exec leaguesphere.app printenv DBACCESS_ENABLED'   # → true
```

## Notes

- Stage dbaccess is currently `true`. The prod/stage `ls.app.prod` runs that day passed
  `-e dbeaver_dbaccess_enabled=true` globally, so the stage entry rendered it too. The next
  stage run without `-e` turns stage off again. That's intended: the stage default stays off.
- Related: `history/2026-11-20_dbaccess-insert-delete.md`.
