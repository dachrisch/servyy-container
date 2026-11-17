# Waggle — Google SSO on the shared bumbleflies client, image on `latest`

**Date:** 2026-11-17
**Type:** Service change
**Status:** Implemented, deployed to `servy.lehel.xyz`
**Relates to:** 2026-11-11_waggle-openpost.md (created the service, pinned the tag)

## Summary

Two changes to Waggle (`waggle.bumbleflies.de`, self-hosted OpenPost):

1. **Google sign-in** is wired to the existing bumbleflies-only Google OAuth
   client — the one already shared by `finance.leaguesphere.app`, `queen` and
   `live.bumbleflies.de`. It is additive: the password login stays.
2. **The image tag moved from a pinned release to `latest`**, the deploy is what
   advances it, and `portainer.watchtower-prod` is allowed to advance it too
   (`scope=prod`).

## Context

The 2026-11-11 deploy pinned `ghcr.io/getopenpost/openpost:${OPENPOST_VERSION:-v7.39.0}`
deliberately — a container holding a post queue plus the key that unseals
provider tokens should not move on its own. In practice two things argued
against the pin:

- Nothing updates it unattended anyway (no watchtower label, no cron), so the
  only thing the pin controlled was *whether a deploy also upgrades*. The
  operator wanted deploys to do that.
- The pinned `OPENPOST_VERSION` lived in interpolation only; the env template
  never set it, so "bump a release" meant hand-editing a compose file.

Separately, every bumbleflies app with a login already uses one Google OAuth
client, and Waggle was the odd one out with a lone password account.

## Decision

**Google SSO — reuse the shared client.** OpenPost v7.x ships a first-party
Google identity provider behind `OPENPOST_AUTH_GOOGLE_CLIENT_ID` /
`OPENPOST_AUTH_GOOGLE_CLIENT_SECRET`; when set, the server registers a `google`
provider (issuer `https://accounts.google.com`, scopes `openid profile email`)
and the login page renders a Google button. Reusing `leagues_finance.*` needs no
new OAuth app and mirrors `bumbleflies/live.env.j2` — two lines in
`waggle.env.j2`.

Callback the app derives from `OPENPOST_PUBLIC_URL` (read from
`apps/server/internal/services/identity/service.go`, not guessed):

```
https://waggle.bumbleflies.de/api/v1/auth/oidc/google/callback
```

**Image — `latest` plus an explicit pull.** `image: …:latest` alone is a trap:
`community.docker.docker_compose_v2` defaults to `pull: missing`, so the first
pulled `latest` would be reused forever and the pin would only have been
replaced by a staler lie. The role gained an opt-in `pull` parameter (same
`omit` pattern as `build`) and waggle opts into `always`.

## Detailed Changes

| File | Change |
|---|---|
| `ansible/plays/roles/docker_service/templates/waggle.env.j2` | New *Sign-in (Google SSO)* section: `OPENPOST_AUTH_GOOGLE_CLIENT_ID`/`_SECRET` from `leagues_finance.*`, with the redirect URI, the "set both or neither" rule and the subject-not-email matching note. |
| `waggle/docker-compose.yml` | `image:` → `ghcr.io/getopenpost/openpost:latest`, interpolation dropped. Header reworded: the tag moves on a deploy *and* under watchtower-prod, and a new release runs migrations, so a failed new image can leave a newer schema behind an older binary. New label `com.centurylinklabs.watchtower.scope=prod`. |
| `ansible/plays/roles/docker_service/tasks/deploy.yml` | New `pull: "{{ compose_pull | default(omit) }}"` on `docker_compose_v2` — `omit` preserves compose's `missing` policy for every other service. |
| `ansible/plays/user.yml` | Waggle role block: `compose_pull: always`. |

No `secrets.yml` change (the client was already there), no new secret, no DNS,
no Traefik change, no other service touched.

## Verification

```bash
# repo pull must be in the tag list: the compose file lives in the remote
# checkout, while the .env is rendered from the controller
cd ansible && ./servyy.sh --limit servy.lehel.xyz \
  --tags "user.docker.repo,user.docker.waggle"

ssh servy.lehel.xyz "docker inspect waggle.openpost --format '{{.Config.Image}}'"
ssh servy.lehel.xyz "docker inspect waggle.openpost --format '{{index .Config.Labels \"com.centurylinklabs.watchtower.scope\"}}'"  # prod
ssh servy.lehel.xyz "docker exec waggle.openpost env | grep AUTH_GOOGLE"
curl -fsS https://waggle.bumbleflies.de/api/v1/ready
curl -fsS https://waggle.bumbleflies.de/api/v1/auth/oidc/providers   # [{"id":"google",...}]
```

`/api/v1/auth/oidc/providers` answered `[]` before the change, which is how the
"nothing was wired" starting point was confirmed.

## Manual step this repo cannot do

The redirect URI must be added to the OAuth client in the Google Cloud Console
(project `391372270100`) as an **Authorized redirect URI**. Until then Google
answers `redirect_uri_mismatch` and the button is decorative. If that consent
screen is still in *Testing* status, only its test users can complete the flow.

## Deliberate choices

- **SSO is a second door, not a replacement.** `OPENPOST_DISABLE_REGISTRATIONS`
  stays `true`, and the app refuses JIT provisioning once any user exists, so a
  Google sign-in cannot create an account here even though the provider is
  compiled with `JITEnabled: true`.
- **No email-based auto-link.** Identity resolution matches the OIDC `subject`
  only; an unlinked identity with an already-registered email aborts with
  `ErrEmailConflict`. Existing password accounts therefore link Google once via
  *Settings → Security*, which is also the safety property: nobody can take over
  an account by owning its email.
- **`latest` under watchtower-prod, no pin.** The 2026-11-11 entry argued the
  opposite (pin per release, no watchtower label); the operator reversed that on
  2026-11-17. Accepted tradeoff: releases arrive within the 2h poll, health
  gating rolls back a container that never becomes healthy — but it can only
  restore the *image*, never the schema the failed release already migrated. A
  bad release that migrates and then fails health is therefore a manual restore
  from `/home/cda/waggle-backup-*.tar.gz`.
- **`stop_grace_period: 60s` is NOT honored by watchtower.** The fork stops
  containers with `--stop-timeout` (= `WATCHTOWER_TIMEOUT`), 10s here, which
  overrides the container's 60s grace. An unattended update can therefore
  SIGKILL a publish in flight. Left as-is — the odds of a 2h poll landing inside
  a delivery are small — but this is the knob to turn (`WATCHTOWER_TIMEOUT=60s`
  in `portainer/docker-compose.yml`, fleet-wide) if a cut-off post is ever seen.

## Impact Assessment

- One container recreated (`waggle.openpost`); data is a bind mount, so the
  database and media are untouched by the recreate.
- The version jump is the substantive risk, not the SSO or the tag syntax: the
  app applies its own migrations at startup.
- From now on this container may restart itself every 2h poll (only when a new
  release exists). A restart interrupts nothing long-lived, but a publish in
  flight is the one thing it can cut (10s SIGTERM, see the stop-timeout note).
- Everything else on the host is unchanged; no other service opted into `pull`.
