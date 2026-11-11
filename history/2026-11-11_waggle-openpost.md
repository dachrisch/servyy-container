# Waggle — self-hosted OpenPost for social post scheduling

**Date:** 2026-11-11
**Type:** New Service
**Status:** Implemented, deployed to `servy.lehel.xyz`

## Summary

Added **Waggle**, a self-hosted [OpenPost](https://openpo.st) instance at
`waggle.bumbleflies.de`, to schedule and publish social posts without a SaaS in
the loop. One container (Go binary, Alpine, uid 1000), SQLite + local media on a
bind mount, published image pinned per release. The name follows the bumbleflies
theme: the waggle dance is how a forager announces *where* and *when* to the
colony — a scheduling metaphor rather than another `social`/`posts` host.

## Reason

Posting to LinkedIn (and later other networks) was manual and lived in an agent
skill. That works for one-off posts but not for a queue: nothing fires while the
laptop is closed, and there is no record of what went out when. OpenPost gives a
composer, a schedule, and per-account readiness — and exposes an HTTP API and an
MCP endpoint, so the same instance can also be driven programmatically.

## Detailed Changes

| File | Change |
|---|---|
| `waggle/docker-compose.yml` | New. `name: waggle`, one service `openpost`, image `ghcr.io/getopenpost/openpost:${OPENPOST_VERSION:-v7.39.0}`, `./data:/data`, `proxy` network, Traefik labels (HTTP→HTTPS redirect + `websecure` router, **HTTP-01** resolver), `stop_grace_period: 60s`, `mem_limit: 1g`. No published ports; no watchtower label. |
| `ansible/plays/roles/docker_service/templates/waggle.env.j2` | New. The compose project `.env`: includes `docker.env.j2` for `SERVICE_HOST`/`SERVICE_NAME`/…, then Traefik interpolation, the three public URLs, storage paths, both secrets, `OPENPOST_TRUSTED_PROXY_CIDRS`, the registration switch and the LinkedIn flags. |
| `ansible/plays/vars/secrets.yml` | New `vault_waggle_jwt_secret` / `vault_waggle_encryption_key` (44-char `lookup('password', …)` seeds). New `docker.services[]` entry `{name: Waggle (OpenPost), dir: waggle, depends: traefik, host: waggle.bumbleflies.de}` so the container-health probe, Pi-hole entry, `host_ping.yml` and `forall_docker_services.sh` all pick it up. |
| `ansible/plays/user.yml` | One `docker_service` role block, `service_dir/service_name: waggle`, `service_host: "{{ waggle_service_host \| default('waggle.bumbleflies.de') }}"`, tag `user.docker.waggle`. |
| `ansible/production` | `waggle: true` on servy; host var `waggle_disable_registrations: false` for the first deploy only. |
| `ansible/plays/roles/user/tasks/docker_extras.yml` | `waggle` added to the `forall_docker_services.sh` list; new task creating `waggle/data/{db,media}` owned by `create_user` — Docker would create a missing bind source as root and the container (uid 1000) then cannot write its database. |
| `.gitignore`, `ansible/.gitignore` | `waggle/data/` and the two generated secret seeds. |

### Deliberate choices

- **HTTP-01 resolver.** `bumbleflies.de` is registered at Strato, so the
  Porkbun-bound `letsencryptdnsresolver` cannot issue for it — same reason as
  `bnb-office`, `queen` and `dontforget`.
- **No DNS change.** `*.bumbleflies.de` is already a wildcard to servy
  (A `49.13.6.173`, AAAA `2a01:4f8:c013:f6f4::1`), so `waggle.` resolved before
  the deploy.
- **Pinned tag, no watchtower label.** The container holds a post queue and the
  key that unseals provider tokens; upgrades are a deploy decision, not an
  unattended pull.
- **Bind mount, not a named volume.** restic's `home` repo backs up
  `source_path: /home/cda`, which is exactly where the checkout (and therefore
  `waggle/data`) lives. A named volume would sit in `/var/lib/docker/volumes`
  and be outside the backup.
- **`OPENPOST_ENCRYPTION_KEY` is load-bearing.** It seals the stored provider
  credentials. A restore with a different key does not error — it silently loses
  every connected account. It lives in git-crypt'd `secrets.yml` so restores are
  reproducible.
- **LinkedIn is member-only for now.** `OPENPOST_LINKEDIN_AUTH_MODE=openid`
  (self-service *Sign In with LinkedIn using OpenID Connect* + *Share on
  LinkedIn*). Organization Pages need LinkedIn's Community Management approval,
  so `OPENPOST_LINKEDIN_ORGANIZATIONS_ENABLED=false`. Thread replies need
  `w_member_social_feed` — a further approval that makes sign-in FAIL on a
  self-service app — hence `OPENPOST_DISABLE_LINKEDIN_THREAD_REPLIES=true`,
  which must be set **before** the first connection.

## Verification

```bash
# after `./servyy.sh --limit servy.lehel.xyz --tags "user.docker.waggle"`
curl -fsS https://waggle.bumbleflies.de/api/v1/ready     # status ready, database ok
docker ps    --filter name=waggle.openpost
docker logs  waggle.openpost --tail 50
ls -l /home/cda/servyy-container/waggle/data/{db,media}
```

## Impact Assessment

- Nothing existing was modified: no role changed, no other service's compose or
  env touched, no DNS record created or altered.
- New public HTTPS host on the existing Traefik, new container
  `waggle.openpost`, ~10 MB idle RSS, 1 GB cap.
- Disk: `waggle/data` grows with published media (43 GB free at deploy time).
  No fixed budget — check it in the first weeks, the host had a disk-reclaim
  exercise on 2026-10-27.

## Rollback Procedure

```bash
# 1. Stop and remove the container (data survives)
cd /home/cda/servyy-container/waggle && docker compose down
# 2. Remove the cert + router by deleting the container, then:
#    set `waggle: false` in ansible/production (servy block) and deploy.
# 3. Optional: git rm -r waggle/ + revert this commit, and delete the
#    waggle/data bind directory (it is not tracked).
```

## Next Steps

1. **Flip `waggle_disable_registrations` to `true`** in `ansible/production` and
   redeploy as soon as the first (administrator) account exists. Signup is open
   until then and the hostname is public.
2. Create the LinkedIn developer app: products *Share on LinkedIn* + *Sign In
   with LinkedIn using OpenID Connect*, redirect URL
   `https://waggle.bumbleflies.de/api/v1/accounts/linkedin/callback`. Store the
   client id/secret as a provider app and connect the member account.
3. Bluesky/Mastodon are direct integrations (no review) and are the cheap next
   targets; the bumbleflies **company page** waits on Community Management
   approval.
4. No SMTP configured, so email verification and password reset do not work yet.
   `vault_gmail_smtp_password` already exists if we want to wire it.
5. MCP endpoint (`/mcp`) is available on the same origin — an agent can draft and
   schedule through it instead of the UI.

## Addendum — media serving: what broke and what did not (same day, later)

Getting AI working produced a long false lead worth writing down.

**Media serving was correct all along.** `publicurl.ResolveMediaURL` signs media URLs
(HMAC-SHA256 over `<media_id>:<exp>`, 15-minute lifetime, key from
`OPENPOST_MEDIA_SIGNING_KEY` falling back to `OPENPOST_ENCRYPTION_KEY`), and the
`/media/:id` route accepts a valid signature without a session. Verified from off-host:

| Request | Result |
|---|---|
| unsigned | `401` |
| signed, valid | `200`, 877 461 bytes |
| signed, expired | `401` |
| signed, wrong signature | `401` |

Positive proof no public mirror was ever needed: the media record carried
`public_url_checked_at=20:39Z` with `public_url_status=200`, hours before any mirror
existed.

**The two false conclusions.** (1) A `401` on `/media/…` looked like broken media
exposure; it was an unsigned request behaving as designed. (2) OpenPost's AI does not
fetch media at all — `internal/ai/openrouter.go` inlines it as a `data:` URL — so the
`Received 401 status code when fetching image from URL` error was produced by my own
`curl`, never by OpenPost. A read-only nginx mirror of `./data/media` was added and has
been **removed**; the stack is back to the documented shape.

**The real bug, still present upstream (v7.39.0), path only — not serving:**

```go
local.go:124        Save() returns path (ABSOLUTE: /data/media/<id>.png)
media.go:3687,3864  that value is persisted as media_attachments.file_path
local.go:160        Open(id) → resolvePath(id)
local.go:238        filepath.Join(baseDir, cleaned)   // treats it as a RELATIVE key
                    ⇒ /data/media + /data/media/<id>.png
```

It breaks **internal** reads (publication build, Ideate) with
`could not read selected asset N` while the UI and the signed public URL keep working,
because those use the basename. Upstream fix: persist the relative key from `Save()` (or
let `resolvePath` accept an absolute path inside `baseDir`). Until then a symlink
`data/media/data -> /data` (created by Ansible in `docker_extras.yml`) makes the doubled
path resolve; remove it once the app is fixed.


## Addendum — the first page load got the owner's own IP banned (same day)

The first browser visit to `https://waggle.bumbleflies.de` rendered a 500 instead of the
app, and the visiting address was banned for 24 h by `loki-blocklist`. Not a Waggle fault;
two pre-existing edge-guard defects that only a chunk-heavy SPA could expose.

**Chain of events.**

1. A cold load of the OpenPost SPA fetched the shell plus ~20 JS chunks, CSS and preloads
   over one HTTP/2 connection — more than `edge-ratelimit`'s `burst: 50`
   (`traefik/dynamic.yaml`). Traefik shed the excess with 429s (`OriginStatus: 0`, never
   reaching the container).
2. SvelteKit could not hydrate, rendered its own error route (the "500 | Internal Error"
   page — not Traefik's branded one), and the browser retried: **776 × 429 in 2 minutes**.
3. The blocklist queries read that as a flood (`traefik-rate-flood attempts=687`,
   `traefik-rate-limit attempts=776`, `traefik-aggressive-crawler attempts=791` at
   20:07:04) and banned the client — the owner's own egress address — on 80/443.

**Fixes (commit `d54f046`).**

| Change | Why |
|---|---|
| `edge-ratelimit` `burst: 50 → 200` | A normal client must never be shed before the app has finished loading. 200 ≈ two SPA cold loads, still a quarter of the 40k+/2m a real flood produces. The 25 r/s sustained rate is unchanged, and the `>=600 req/min` backstop query carries the flood signal. |
| `get_error_ips` excludes 429 | 429 is *our* limiter shedding, not a client probing, and it already has a purpose-built 2-minute signal. Counting it turned a limiter misfire into a re-ban every hour for the rest of the day (`>=100 4xx/24h`). RE2 has no lookahead, so 4xx-minus-429 is enumerated by range. |

**Second trap found while applying it.** `dynamic.yaml` is a single-file bind mount, so a
`git` checkout swaps the inode and the container keeps serving the old file — a deploy
appears applied while nothing changes. The config was written through the container
(`docker exec -i ... cat > /etc/traefik/dynamic.yaml`) so `watch: true` reloaded it without
a restart; 80 parallel requests then returned 80 × 200 (21 × 429 before). Documented in
`traefik/AGENTS.md`.

**Verification.** Browser load: welcome screen with Sign In / Create Account, no console
errors. `curl` burst 80/80 → 200. Unbanned by hand
(`fail2ban-client set loki-blocklist unbanip …`) — the historical 429 lines would otherwise
have kept us banned through the hourly `full` run.
