# Public repos on ci.lehel.xyz are anonymously readable

**Date:** 2026-11-24
**Status:** ✅ Live on servy.lehel.xyz after `--tags user.docker.repo,user.docker.ci`
**Relates to:** `ci/AGENTS.md` "Sign in", `history/2026-11-23_ci-server.md`

## Change

`FORGEJO__service__REQUIRE_SIGNIN_VIEW` changed from `true` to `false` in
`forgejo.env.j2`. Registration stays closed (`DISABLE_REGISTRATION=true`), so
only accounts created by an admin exist; private repos still require sign-in and
writes still require a token or SSH key.

This was needed so `cda/dontforget` — already marked `private: false` — is
actually readable via a public link. Previously the global sign-in gate meant
"public" repos were effectively internal.

## Verification

- `curl -s -o /dev/null -w '%{http_code}' https://ci.lehel.xyz/cda/dontforget` → **200**, no redirect.
- `GIT_TERMINAL_PROMPT=0 git ls-remote https://ci.lehel.xyz/cda/dontforget.git HEAD` → returns a ref anonymously.
- `https://ci.lehel.xyz/user/login` still 200; the custom sign-in page is intact.
- Deploy recap: `ok=223 changed=3 failed=0`.

## Follow-up

Contributor accounts are still to be created by name; registration remains
closed. `CONTRIBUTING.md` was added to `cda/dontforget` master (commit
`ec8fb98`) and is anonymously readable (HTTP 200); it documents fork/branch →
conventional commit → PR → green CI → Knope release. No accounts were created
yet.
