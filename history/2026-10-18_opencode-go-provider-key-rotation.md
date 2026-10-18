# 2026-10-18 — opencode service: rotate opencode-go provider API key

## Goal

Rotate the `opencode-go` LLM **provider** credential used by the server-side
opencode container (`codey.lehel.xyz`, container `opencode.web`). A new key was
issued and the old one retired.

This is the provider key (`oc_sk_…`), i.e. the credential in the `provider`
block of the generated `opencode.json` — **not** the API-access key
(`opencode.api_key`, sent by clients as `X-Api-Key` through the authgate) and
**not** `OPENCODE_SERVER_PASSWORD` (the UI Basic-auth password). Those are
separate secrets and were left untouched.

## Change

1. `ansible/plays/vars/secrets.yml` (git-crypt encrypted) —
   `opencode.opencode_go_api_key` replaced with the new `oc_sk_…` value. Single
   source of truth for every `opencode.*` secret; the raw key is not recorded
   here.
2. `ansible/plays/roles/docker_service/templates/opencode/.env.j2` — already
   renders it to `opencode.env` (mode `0600`) as
   `OPENCODE_GO_API_KEY={{ opencode.opencode_go_api_key }}`; no template change
   needed.
3. `opencode/scripts/startup.sh` — already `envsubst`s `OPENCODE_GO_API_KEY`
   into `/root/.config/opencode/opencode.json` from
   `opencode.json.template` on every boot; no script change needed.

Deploy recreates the container (env_file change), and the re-run entrypoint
regenerates `opencode.json` with the new key.

## Deploy

```bash
cd ansible && ./servyy-test.sh --tags "user.docker.opencode"
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit codey.lehel.xyz
```

## Verification

- `opencode.env` on both hosts shows the new `OPENCODE_GO_API_KEY`.
- Container env (`docker exec opencode.web env | grep OPENCODE_GO`) shows it.
- After boot, `/root/.config/opencode/opencode.json` has the new key on
  `provider.opencode-go.options.apiKey` (startup regenerates it; the old key
  persists in the JSON until the container boots, so verify after `healthy`).
- Container reaches `Up (healthy)` on `codey.lehel.xyz`.

## Notes / follow-ups

- Because `/root` persists via the `opencode_root` volume, the previous key
  lingers in `opencode.json` until the container reboots and startup.sh
  rewrites it — a `docker compose restart` is enough if a deploy ever leaves the
  container running with a stale config.
- If the same key is used on the developer box (`setup-home`) or anywhere else,
  rotate it there too.
