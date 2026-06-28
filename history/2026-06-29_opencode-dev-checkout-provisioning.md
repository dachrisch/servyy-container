# OpenCode Dev-Checkout Self-Provisioning

**Date:** 2026-06-29
**Status:** ✅ Deployed to production (lehel.xyz)
**Branch:** `claude/opencode-dev-provisioning` → merged to `master` (b534871)
**Plan:** `docs/superpowers/plans/2026-06-27-opencode-dev-checkout-provisioning.md`

## Problem

After an opencode volume restore, only the opencode **database** (session history) came
back. The working trees under `/root/dev` and all git plumbing (`~/.ssh`, `~/.gitconfig`,
`gh` auth) were gone. opencode sessions referenced `~/dev/leaguesphere` etc., but the
directories no longer existed — the projects were "not checked out". The checkouts and the
SSH key had only ever been **manually seeded once** into the `opencode_root` named volume
(documented as a one-time manual step in the Feb-16 named-volume migration), so they were
not reproducible and did not survive a rebuild.

## Solution

The container now **self-provisions on every boot**. Secrets + a declared repo list live in
git-crypt-encrypted `secrets.yml`, are rendered into `opencode.env`, and a new idempotent
`provision-dev.sh` (called from `startup.sh`) writes credentials, clones/pulls the repos,
and git-crypt-unlocks the infra checkout. A volume rebuild now self-heals.

### Repos provisioned into `/root/dev`

| dir | repo | branch | git-crypt |
|---|---|---|---|
| leaguesphere | dachrisch/leaguesphere | master | no |
| league.finance | dachrisch/league.finance | master | no |
| groceries | dachrisch/groceries-order-tracking | master | no |
| energy | dachrisch/energy.consumption | **main** | no |
| servyy-container | dachrisch/servyy-container | master | **unlock** |

### Auth mechanisms

- **GitHub:** fine-grained PAT (HTTPS clone/push via `x-access-token` credential helper). One
  token covers all repos. No deploy keys.
- **git-crypt:** the repo's symmetric key (`git-crypt export-key`, base64) is shipped in
  `opencode.env`; `provision-dev.sh` runs `git-crypt unlock` on the `servyy-container` checkout.
- **SSH to host (`servy.lehel.xyz`):** a dedicated ed25519 key, reached over the internal
  docker bridge via `host.docker.internal` (host-gateway) — **no public hairpin**. The public
  key is authorized on the `cda` user **scoped to local docker networks** with
  `from="172.16.0.0/12,127.0.0.1"`, so it is useless from the internet even if leaked.

## Files Changed

- `ansible/plays/vars/secrets.yml` — `opencode:` block: `github_pat`, `git_crypt_key_b64`,
  `servy_ssh_key_b64`, `servy_ssh_pubkey`, `dev_repos` list (git-crypt encrypted).
- `ansible/plays/roles/docker_service/templates/opencode/.env.j2` — emit `GITHUB_PAT`,
  `GIT_CRYPT_KEY_B64`, `SERVY_SSH_KEY_B64`, `DEV_REPOS_B64` (`dev_repos | to_json | b64encode`).
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` — assert the
  new opencode.env vars render.
- `opencode/scripts/provision-dev.sh` — **new** idempotent provisioning script.
- `opencode/scripts/startup.sh` — call `provision-dev.sh` before launching the app.
- `opencode/docker-compose.yml` — `extra_hosts: ["host.docker.internal:host-gateway"]`.
- `ansible/plays/roles/user/tasks/docker_extras.yml` — `authorized_key` task (from=-scoped).

## Deployment

```bash
# merged feature branch to master (fast-forward), pushed
cd ansible && ./servyy.sh --tags "user.docker.repo,user.docker.opencode,user.docker.env" --limit lehel.xyz
ssh lehel.xyz "docker restart opencode.web"   # triggers provisioning
```

## Verification (prod)

- `docker exec opencode.web ls /root/dev` → 5 checkouts (energy, groceries, league.finance,
  leaguesphere, servyy-container). ✅
- Infra checkout git-crypt unlocked: `filter.git-crypt.smudge` set, `secrets.yml` reads as
  plaintext YAML. ✅
- SSH key `id_servy` (0600) + config present; live test
  `docker exec opencode.web ssh -o BatchMode=yes servy.lehel.xyz 'hostname; whoami'`
  → `servy` / `cda`. ✅
- `authorized_keys` carries `from="172.16.0.0/12,127.0.0.1" ... opencode-container-servy`. ✅
- Idempotent across restart (servyy-test): 2nd boot = "updating" + "already git-crypt
  unlocked", no re-clone. ✅
- The Gemini `auth.json` (added earlier to fix provider auth) **survived** the container
  recreate (named volume `opencode_root`). ✅

Validated end-to-end on `servyy-test.lxd` before production.

## Security Notes / Trade-offs

- The **git-crypt master key in the container** grants full infra-secret decryption to anyone
  with container access — accepted, because infra work inside opencode requires it.
- The **PAT** has `contents: read+write` (not rotated, per decision); lives in `opencode.env`
  + volume. Consider downscoping to read-only later.
- SSH access is a **dedicated** key, network-scoped (`from=`) and reached only over the docker
  bridge — independently revocable without affecting the user's personal key.

## Notes for Next Time

- Molecule cannot run on the dev workstation (no Docker daemon); it runs in CI on push and on
  servyy-test. The env-rendering change was additionally validated locally via an Ansible
  `template` render.
- The SSH-hairpin risk anticipated in the plan did **not** materialize: `host.docker.internal`
  (host-gateway → `172.17.0.1`) routes container→host over the bridge cleanly; no fallback
  needed.
- `git merge --no-ff` failed with `fatal: stash failed` in this workstation's git
  environment; a fast-forward merge (master was a direct ancestor) succeeded.
