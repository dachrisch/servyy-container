---
name: managing-ci
description: Use when creating, listing, deleting or mirroring repositories on ci.lehel.xyz (Forgejo), adding SSH or deploy keys there, setting Actions secrets or variables, checking runner status or workflow runs, looking at packages or the container registry, or doing anything else through the Forgejo API — and whenever an ci.lehel.xyz API call needs credentials.
---

# Managing ci.lehel.xyz (Forgejo)

All API work goes through `fj` (next to this file) with the **managed API
token**. Never use the admin password: password basic auth on the API is being
switched off, and it was the way secrets leaked into transcripts before.

```bash
FJ=.claude/skills/managing-ci/fj      # from the servyy-container repo root
$FJ GET /user                          # sanity check -> "login":"cda"
```

## The token

| | |
|---|---|
| Local copy | `~/.config/forgejo/ci.lehel.xyz.token` (0600; `ci.servyy-test.lxd.token` for test) |
| Vaultwarden | item `forgejo - api token (ci.lehel.xyz)` (source of truth together with the local copy) |
| Scopes | `all`, user `cda`, named `ansible-manage-<utc timestamp>` |
| Managed by | `ansible/plays/forgejo_api_token.yml` → `roles/forgejo_bootstrap/tasks/api_token.yml` |

**Missing local copy** (new machine, deleted file): restore it, never mint by hand:
```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags user.docker.ci.token
```
That takes the Vaultwarden copy (needs `~/.ssh/vw.key`), validates it against
the API and writes the file. It mints a new token **only** when Forgejo rejects
every copy (401). A mint leaves the previous `ansible-manage-*` token alive: tell
the user to revoke it in the UI (Settings → Applications) — the API cannot list or
delete tokens without basic auth.

## Rules

- **Never print the token.** Not `cat` the file, not `bw get`, not `echo`. `fj`
  feeds it to curl on stdin; keep it that way in any ad-hoc call
  (`printf 'header = "Authorization: token %s"\n' "$(cat file)" | curl -K - …`).
- **Never read `ansible/plays/vars/secrets.yml`** or grep across the repo without
  `--exclude=secrets.yml --exclude='*.env'` — the repo is git-crypt unlocked.
- **Confirm before destructive calls** (DELETE of a repo, key, secret, user,
  package) unless the user asked for exactly that object to go.
- Test host: `FJ_DOMAIN=servyy-test.lxd FJ_BASE=http://127.0.0.1 FJ_HOST=ci.servyy-test.lxd`
  works only **on** servyy-test (its name does not resolve elsewhere) — prefer
  running the API checks on production unless the task is about the test host.

## Recipes

API reference: `https://ci.lehel.xyz/api/swagger` (signed in). Paths are relative
to `/api/v1`; `fj` adds the prefix.

**Repositories**
```bash
$FJ GET  '/user/repos?limit=50'
$FJ POST /user/repos '{"name":"<repo>","private":true,"auto_init":false}'
$FJ GET  /repos/cda/<repo>
$FJ PATCH /repos/cda/<repo> '{"description":"…","default_branch":"master"}'
$FJ DELETE /repos/cda/<repo>                                  # confirm first
```

**Migrate / mirror from GitHub** (`mirror:true` = pull mirror, re-synced by Forgejo).
A private GitHub repo needs `"auth_token":"<github token>"` — pass it through a
file (`@body.json` in the scratchpad, deleted afterwards), never inline.
```bash
$FJ POST /repos/migrate '{"clone_addr":"https://github.com/dachrisch/<repo>.git","repo_owner":"cda","repo_name":"<repo>","service":"github","private":true,"mirror":false}'
```

**Push mirror to GitHub** (Forgejo pushes on every commit):
```bash
$FJ POST /repos/cda/<repo>/push_mirrors @body.json   # {"remote_address":…,"remote_username":…,"remote_password":<token>,"sync_on_commit":true,"interval":"8h0m0s"}
$FJ GET  /repos/cda/<repo>/push_mirrors
```

**Keys**
```bash
$FJ GET  /user/keys                                                    # account SSH keys
$FJ POST /user/keys "{\"title\":\"<name>\",\"key\":\"$(cat ~/.ssh/<key>.pub)\"}"
$FJ POST /repos/cda/<repo>/keys "{\"title\":\"deploy\",\"key\":\"$(cat <key>.pub)\",\"read_only\":true}"
```

**Actions secrets and variables** (secrets are write-only; the value goes in a
body file, never in the command line)
```bash
$FJ PUT  /repos/cda/<repo>/actions/secrets/<NAME> @secret.json        # {"data":"…"}
$FJ GET  /repos/cda/<repo>/actions/secrets                            # names only
$FJ POST /repos/cda/<repo>/actions/variables/<NAME> '{"value":"…"}'
$FJ GET  /repos/cda/<repo>/actions/variables
```
User-wide: the same paths under `/user/actions/…`.

**Runs and runners**
```bash
$FJ GET '/repos/cda/<repo>/actions/tasks?limit=20'      # recent jobs: status, workflow, head_sha
$FJ GET /admin/actions/runners                           # GLOBAL runners only (codey): status idle|active|offline
$FJ GET /user/actions/runners                            # owner-scoped runners (runny, scope cda)
$FJ POST /repos/cda/<repo>/actions/workflows/<file.yml>/dispatches '{"ref":"master"}'
```
Runner and runs background (labels, which runner builds what): `ci/AGENTS.md`
"Running CI" and `runny/AGENTS.md`.

**Packages / registry**
```bash
$FJ GET '/packages/cda?type=container'
$FJ DELETE /packages/cda/container/<image>/<tag>        # confirm first
```
`docker login ci.lehel.xyz -u cda` takes a token (scope `write:package`) as the
password; for CI jobs store one as an Actions secret.

## Related

- Server side, deploy, backup, theme: `ci/AGENTS.md`.
- Git over SSH (`git@ci.lehel.xyz`, client key `~/.ssh/ci_lehel` from setup-home):
  `ci/AGENTS.md` "Git over SSH".
