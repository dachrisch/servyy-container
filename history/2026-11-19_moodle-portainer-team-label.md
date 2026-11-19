# `moodle.moodle` in the Portainer team `leaguesphere`

**Date:** 2026-11-19
**Branch:** `db-tier/wp12-wp13-r10`
**Plan:** [docs/plans/2026-11-19_moodle-portainer-team-label.md](../docs/plans/2026-11-19_moodle-portainer-team-label.md)

## What changed

`moodle/docker-compose.yml`, `services.moodle.labels` gained one line:

```yaml
- io.portainer.accesscontrol.teams=leaguesphere
```

Nothing else. The value is the team **name**, the same convention the `leaguesphere/*` stacks use.
Deliberately **not** labelled:

- `db-business.mariadb` — it also serves bnb-office, so a label would hand the team bnb's database;
- `moodle.db` — the exited rollback container (and it no longer exists on the host at all; see below).

`moodle/AGENTS.md` documents the label (a hand `compose up` must keep it) and its stale layout table
now names the business tier instead of `moodle.db`.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,user.docker.moodle \
  -e docker_branch=db-tier/wp12-wp13-r10
```

`17:58:03Z → 18:00:55Z`, `changed=3`, `failed=0`. `moodle.moodle` was recreated at `18:00:03Z`
(created timestamp changed, same image `erseco/alpine-moodle:4.5.16`).

## Incident during the deploy — an offd.de outage of ~6 minutes

The first recreate **crash-looped** (`Restarting`, offd.de 502):

```
mysqli::__construct(): (HY000/1045): Access denied for user 'moodle'@'192.168.48.4' (using password: YES)
```

Cause, and it is a trap for every future branch deploy from a **new worktree**: several secrets in
`plays/vars/secrets.yml` are `lookup('password', 'vars/.<name> …')`, which **generates and stores the
value on first use in whatever checkout runs Ansible**. A fresh `git worktree` does not inherit those
untracked seed files, so the run generated *new* passwords and rendered them:

- `DB_PASS` in `moodle/app.env` → rejected by the live `moodle` user (grant `'moodle'@'%'` exists, only
  the password differed) → the container never reached the database;
- `MOODLE_PASSWORD` (admin) was generated too. It was never applied: the image only rewrites the admin
  user *after* a successful DB connect, which never happened.

Nothing was rotated on the server, so the repair was to restore the seeds and re-render:

```bash
cp -p <canonical>/ansible/plays/vars/.{dbops_password_*,monitor_grafana_admin_password,moodle_*,\
restic_password_*,vaultwarden_admin_token,waggle_*} <worktree>/ansible/plays/vars/
./servyy.sh --limit servy.lehel.xyz --tags user.docker.moodle        # 18:04:33Z → 18:06:17Z
```

All 16 seed files were then byte-identical (sha256) to the canonical checkout. Second recreate
`18:05:35Z`, healthy by `18:06:1xZ`.

**Measured outage on `offd.de`: `18:00:03Z` → ~`18:06:15Z` (~6 min)**, of which all but the normal
recreate was this mistake. The intended downtime is the recreate itself: ~40 s to a healthy
container.

## Verification (after the fix, 18:07Z)

```
docker inspect moodle.moodle
  created=2026-11-19T18:05:35Z  status=running  health=healthy
  label=leaguesphere
offd.de                          200  0.85 s
www.offd.de                      -> apex (301 path, unchanged)
nginx log (inside the container)  GET /mod/forum/view.php?id=1658 200   (DB-backed page)
```

Portainer (CE 2.45.3, endpoint 1 = servy), via `GET /api/endpoints/1/docker/containers/<name>/json`:

| container | `Portainer.ResourceControl` |
|---|---|
| `moodle.moodle` | `Id=226, Type=1, Public=False, TeamAccesses=[{TeamId: 1, AccessLevel: 1}], UserAccesses=[]` |
| `leaguesphere.app` (reference) | `Id=220, Type=1, Public=False, TeamAccesses=[{TeamId: 1, AccessLevel: 1}]` |
| `db-business.mariadb` | none |

`GET /api/teams` → `[(1, 'leaguesphere')]`. So Portainer created the resource control from the label
by itself; the team reaches exactly this one container.

The database tier was not touched: `db-business.mariadb` `created=2026-11-19T09:44:24Z`, still
`running` (no recreate, no restart).

Note: `moodle.db` **does not exist** on the host any more (`no such object`) — the stopped WP-7b
rollback container was pruned before this package. The rollback path is the `data/mariadb` datadir,
not `docker start moodle.db`; `moodle/docker-compose.yml`'s rollback comment still says the container
is "stopped, not deleted" and should be corrected when that compose is next touched.

## Rollback

Revert the label and redeploy `--tags user.docker.moodle`; delete the `ResourceControl` (or remove the
label and let Portainer re-discover). The team's access is `AccessLevel: 1`, the same level the
leaguesphere containers already grant.

## Do not undo

- Do not put the label on `db-business.mariadb` — it serves bnb-office.
- Do not deploy from a checkout that lacks the `plays/vars/.<name>` seed files; if in doubt, compare
  them against the canonical checkout before running anything that touches a live credential.
- Do not "regenerate" `vault_moodle_db_password` or `vault_moodle_admin_password`: the value is the
  seed file, and a new seed is a new password the server does not know.
