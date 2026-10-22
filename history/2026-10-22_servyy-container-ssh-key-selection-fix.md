# 2026-10-22 — servyy-container: make the GitHub deploy key work outside Ansible

## Goal

Restore a working `git pull` in `/home/cda/servyy-container` on `servy.lehel.xyz`
and `codey.lehel.xyz` while keeping the SSH remote that
[`ea99572`](ansible/plays/roles/user/tasks/includes/github_deploy_key.yml)
introduced for the Ansible repo-sync.

The reported symptom was `git pull` failing on both hosts, initially suspected to
be GitHub revoking SSH keys. It was not.

## Root cause

Nothing was revoked. Checked with the `gh` CLI:

- Repo deploy key `servyy-container-repo-sync (read-only, cda@codey+lehel)`,
  id `162109862`, created `2026-09-02`, still present and unchanged.
- Account keys intact; `delly` still authenticates as `dachrisch` with its agent-held `id_rsa`.
- The hosts' private key `/home/cda/.ssh/id_servyy_container_deploy`
  (`SHA256:IFnvl2kTBckqYo37uqL8WF9Zcya3TNvDBfdhOz4aoCc`, identical to the seed
  `ansible/plays/vars/.servyy-container_deploy_key`) **still authenticates**:
  `ssh -i ~/.ssh/id_servyy_container_deploy -T git@github.com`
  → `Hi dachrisch/servyy-container!`

The real defect is SSH **identity selection**, not authentication:

1. `ea99572` (2026-09-02) moved `docker.repo` to `git@github.com:…` so the
   Ansible `git` module could use `key_file:` and stop hanging on GitHub's
   anonymous-HTTPS 401.
2. `key_file:` is **transient** — the module only exports it for its own run.
3. An interactive `git pull` therefore runs plain `ssh`, which offers the default
   identities (`id_rsa`, `id_ecdsa`, `id_ed25519`, agent). None exist on the
   hosts, and none is the deploy key, so GitHub returned
   `git@github.com: Permission denied (publickey)`.
4. There was no `Host github.com` block in `/home/cda/.ssh/config` on either
   host (only the `storagebox` block) — nothing ever told ssh to use the deploy
   key.

Manually switching the remote to HTTPS "fixed" it (anonymous read of a public
repo works again from these IPs), but that is not durable: `repository.yml`'s
`git` module rewrites `remote.origin.url` from `docker.repo` on every deploy, so
the next run silently reverts it to SSH and re-breaks the pull.

The `opencode` container was never affected — it sets
`GIT_SSH_COMMAND=ssh -i /root/.ssh/id_github` and uses a *user*-scoped key
(`Hi dachrisch!`).

## Decision

Make the deploy key the default identity for `github.com` on the hosts, so the
same key serves both Ansible's `key_file:` path and interactive `git`. Manage
that config from Ansible so it survives reprovisioning and cannot drift again.

Rejected: reverting `docker.repo` to HTTPS — reintroduces the anonymous-fetch
401/hang that `ea99572` was written to escape, and leaves the servers
unauthenticated.

## Changes

- `ansible/plays/roles/user/tasks/includes/github_deploy_key.yml` (MODIFY) — new
  `blockinfile` task writing a marked block to `~/.ssh/config`:

  ```
  Host github.com
      HostName github.com
      User git
      IdentityFile ~/.ssh/id_servyy_container_deploy
      IdentitiesOnly yes
  ```

  `blockinfile` is used (rather than `copy`/`template`) so the pre-existing
  `storagebox` block in the same file stays untouched: only the delimited region
  is owned by Ansible. `IdentitiesOnly yes` prevents ssh from offering the
  non-existent default identities first.

No key was generated or rotated — the seed file existed and matched the deployed
key, so the `opencode_allow_key_generation`-style guard was not involved.

## Verification

- `ansible-playbook plays/user.yml --syntax-check` → OK
- `ansible-lint` (production profile) → 0 failures; `yamllint` → OK
- `./servyy.sh --limit servy.lehel.xyz --tags user.repo` → `changed=2`
- `./servyy.sh --limit codey.lehel.xyz --tags user.repo` → `changed=2`
- Second combined run `--limit 'servy.lehel.xyz,codey.lehel.xyz'` → `changed=0`
  (idempotent — the durability check that `ea99572` lacked)
- On both hosts, after the runs:
  - `cat ~/.ssh/config` — marked block present, `storagebox` block preserved,
    `0600 cda:cda`
  - `ssh -o BatchMode=yes -T git@github.com` → `Hi dachrisch/servyy-container!`
  - `git remote get-url origin` → `git@github.com:dachrisch/servyy-container.git`
  - `git pull` → `Already up to date.` (codey fast-forwarded `8333112 → 952bb98`
    during the first run)
  - no tracked working-tree modifications before or after

Scope checked, deliberately left alone: `~/.zprezto`
(`https://…/my-prezto.git`) and `~/dev/leaguesphere`
(`https://…/leaguesphere.git`) on servy, plus `~/.zprezto` on codey — all
anonymous HTTPS, all fetching cleanly. They do not share this defect.

## Impact

- Interactive `git pull`/`git fetch` over SSH now works on both hosts, and the
  SSH remote is no longer a trap that breaks after manual use.
- Ansible repo-sync behaviour is unchanged (`key_file:` still wins inside the
  play).
- The deploy key is **read-only and repo-scoped**: the servers can pull
  `servyy-container` but cannot push, and `git@github.com:` for other repos still
  fails. That is by design (`ea99572`); a write key would need separate approval.

## Rollback

Delete the `# BEGIN/END ANSIBLE MANAGED - servyy-container GitHub deploy key`
block from `/home/cda/.ssh/config` on both hosts (the markers make it
unambiguous), or remove the `blockinfile` task and run `--tags user.repo`. To
abandon SSH entirely, revert `docker.repo` in `ansible/plays/vars/secrets.yml:42`
to the HTTPS URL.

## Key learnings

- **`key_file:` does not configure the host.** The Ansible `git` module's
  `key_file` is run-scoped; anything else in that checkout (`git pull` by hand,
  a cron job, an interactive shell) uses the default ssh identities. When you
  change a remote from HTTPS to SSH for Ansible's benefit, also make the key the
  default identity — otherwise you fix the automation and break the humans.
- **`remote.origin.url` is Ansible-owned.** Any manual `git remote set-url`
  inside a repo managed by `repository.yml` is overwritten on the next deploy, so
  manual remote fixes there are never durable.
- **Verify keys before believing a revocation story.** `gh api
  repos/<owner>/<repo>/keys` plus `ssh -i <key> -T git@github.com` distinguishes
  "revoked" from "wrong identity" in seconds; the failure message
  (`Permission denied (publickey)`) is identical for both.
- **Idempotency is the regression test.** Running the play twice (`changed=0`)
  is what would have caught the original `ea99572` gap; a single green run hides
  it.
