# 2026-10-22 — Traefik dashboard password rotation + Vaultwarden backup

## Goal

The Traefik dashboard (`https://traefik.lehel.xyz`) was protected by a Basic
Auth hash hardcoded in `traefik/docker-compose.yml` whose password was literally
`admin` (verified: `openssl passwd -apr1 -salt 8EVjn/nj admin` reproduces the
committed hash byte-for-byte). Rotate it to a generated passphrase, keep the
credential where the other important secrets live (git-crypt'd
`ansible/plays/vars/secrets.yml` + a gitignored seed file), and mirror it into
Vaultwarden.

While in there: stop prompting for the Vaultwarden master password on every run
(read it from `~/.ssh/vw.key` instead) and move the Porkbun ACME keys out of the
traefik compose file.

## Change

### Dashboard basic auth: seed → hash → users file

- **Source of truth:** gitignored seed `ansible/plays/vars/.traefik_dashboard_password`
  (mode 0600, one line) holding a 5-word passphrase
  (`bw generate --passphrase --words 5 --separator - -c --includeNumber`).
  Word-based on purpose: it is typed by a human at the browser prompt.
  Constraint: no `:` (htpasswd's field separator).
- `ansible/plays/vars/secrets.yml` exposes it as `traefik_dashboard_password`
  (`lookup('file', …, errors='ignore')`: defined-but-empty when the seed is
  absent, so CI/other hosts don't break; the role fails loudly instead) plus
  `traefik_dashboard_username: traefik`.
- New role `ansible/plays/roles/traefik_dashboard_auth/`:
  - asserts the seed is present/long/no-colon,
  - derives the APR1 salt as `sha256(passphrase)[:8]` (**deterministic**: the
    rendered hash is stable across routine deploys — no file churn — while a
    rotated seed naturally yields a new salt+hash),
  - computes the entry with `openssl passwd -apr1 -salt <salt> -stdin` (password
    on stdin, never in argv; `no_log`),
  - exposes it as the `traefik_dashboard_auth_users` fact,
  - pushes the plaintext to Vaultwarden as a Login item
    `traefik - dashboard basic auth (traefik.lehel.xyz)` (username `traefik`,
    notes pointing at the seed) via the shared `vaultwarden` role. Guarded like
    `vaultwarden_admin_token`: production host only + master password supplied.
- Rendered by `roles/docker_service/templates/traefik/dashboard-auth.htpasswd.j2`
  (Jinja comments only — htpasswd parsers treat every non-empty line as an
  entry) into `traefik/dashboard-auth.htpasswd`, mode 0600.

### Middleware moved from Docker labels to the file provider

The hash used to live in a label
(`traefik.http.middlewares.traefik-auth.basicauth.users=admin:$$apr1$$…`).
That has two drawbacks: `$` must be escaped as `$$` for Compose interpolation,
and rotating the password requires recreating the traefik container (a brief
outage for every site).

- `traefik/dynamic.yaml` now defines the middleware in the file provider:
  `traefik-auth: basicAuth: {usersFile: /etc/traefik/dashboard-auth.htpasswd, realm: Traefik Dashboard}`.
- `traefik/docker-compose.yml` mounts the file read-only and its routers
  reference `traefik-auth@file`; the label-defined middleware is gone. The file
  content never passes through Compose interpolation, so no `$$` escaping.
- `provider.file.watch: true` was already enabled → **password rotations now
  only change a file; Traefik reloads its config and the container is not
  recreated.**

⚠️ Failure mode to know about: if `dynamic.yaml` ever fails to load, the
dashboard would be served **without** auth (fail-open). The post-deploy check
below (anonymous request must return 401) is the guard.

### Porkbun ACME keys out of the compose file

`PORKBUN_API_KEY` / `PORKBUN_SECRET_API_KEY` were hardcoded in
`traefik/docker-compose.yml`. They now come from `traefik/traefik.env`
(`env_file`), rendered from `traefik.porkbun_*` in `secrets.yml`. **Values are
unchanged** — this is a relocation, not a key swap. Note these are a *different*
Porkbun key pair than the `porkbun_api` block used by the DNS role/agent;
swapping them could silently break DNS-01 certificate renewal (which only shows
up at renewal time), so that reconciliation was deliberately not attempted.

### Vaultwarden master password from `~/.ssh/vw.key`

`ansible/servyy.yml`'s `always`-tagged play no longer uses `vars_prompt`:

1. reads `~/.ssh/vw.key` (trimmed) when the variable isn't already set,
2. prompts (`pause`, `echo: false`, run-once) **only** when that file is missing,
3. `-e vw_master_password=…` still wins over both.

Consequences: no more prompt on every `servyy.sh` run (including `--tags`
runs), and Vaultwarden pushes now fire by default instead of needing a typed
master password. Deliberately **not** `cacheable: true` — `ansible.cfg` uses a
jsonfile fact cache in `/tmp/ansible_facts`, and the master password must not be
written to disk there.

## Files

- Added: `ansible/plays/roles/traefik_dashboard_auth/{defaults,tasks,molecule/default/*}`,
  `ansible/plays/roles/docker_service/templates/traefik/{dashboard-auth.htpasswd.j2,traefik.env.j2}`,
  this history file.
- Changed: `ansible/servyy.yml`, `ansible/plays/user.yml`,
  `ansible/plays/vars/secrets.yml` (git-crypt), `ansible/.gitignore`,
  `traefik/docker-compose.yml` (git-crypt), `traefik/dynamic.yaml`,
  `.github/workflows/ci.yml` (molecule matrix), `CLAUDE.md`.
- Not in git: `ansible/plays/vars/.traefik_dashboard_password` (seed — belongs in
  the disaster-recovery backup set, like the restic/admin-token seeds).

## Verification

```bash
# static
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && ansible-lint plays/roles/traefik_dashboard_auth plays/user.yml servyy.yml
cd ansible/plays/roles/traefik_dashboard_auth && molecule test   # CI also runs it

# the seed resolves from plays/vars and hashes deterministically
cd ansible && ansible-playbook servyy.yml -i production --tags always --limit servy.lehel.xyz
#   → "Read the Vaultwarden master password from ~/.ssh/vw.key" = ok, prompt = skipped

# deploy (prompt no longer appears; the Vaultwarden item is created)
cd ansible && ./servyy.sh --tags user.docker.traefik

# live checks
curl -sI https://traefik.lehel.xyz | head -1                       # 401 without credentials
curl -sI -u 'traefik:<passphrase>' https://traefik.lehel.xyz/dashboard/ | head -1   # 200
curl -sI -u 'admin:admin' https://traefik.lehel.xyz | head -1      # 401 (old creds dead)
ssh lehel.xyz "docker exec traefik.traefik ls -l /etc/traefik/dashboard-auth.htpasswd"
ssh lehel.xyz "docker logs traefik.traefik --tail 50"              # no middleware/ACME errors
curl -sI https://pass.lehel.xyz | head -1                          # other vhosts unaffected
```

## Rollback

`git revert` and redeploy `--tags user.docker.traefik`. If the dashboard must be
restored instantly on the host without a revert: write the old
`admin:$apr1$…` line into `/var/lib/docker/.../traefik/dashboard-auth.htpasswd`
(bind mount source in `~/servyy-container/traefik/`) — the file provider picks
it up within seconds.

## Follow-ups

- The two Porkbun key pairs (`porkbun_api` vs `traefik.porkbun_*`) should be
  reconciled after verifying both have the same DNS scope; do it outside a
  renewal window and force a test issuance first.
- `ansible/.vw_master_pw` (gitignored, manually dropped) is now unused — the
  supported location is `~/.ssh/vw.key`.
