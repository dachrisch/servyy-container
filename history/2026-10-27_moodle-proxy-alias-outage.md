# Moodle's `app` service name took leaguesphere.app down — fixed by renaming it

**Date:** 2026-10-27
**Commit:** `e807aff` (rename), `2c4d32c` (probe/ping/extras registration)
**Reported by:** the concurrent session's audit — see
[2026-10-27_checkout-permissions-safety-net.md](2026-10-27_checkout-permissions-safety-net.md)

## What happened

The new `moodle` compose project declared its Apache container as service **`app`** and attached it
to the shared `proxy` network. Compose registers every service name as a **DNS alias** on the
networks it joins — so from that moment, `app` resolved to *both* LeagueSphere's backend and Moodle.

LeagueSphere's frontend reverse-proxies to `app:8000` with a variable `proxy_pass` and
`resolver ... valid=5s`, i.e. it re-resolves the name every 5 seconds. Some requests therefore went
to Moodle, which answers `:80`, not `:8000` → **502** → `leaguesphere.www` failed its healthcheck →
**Traefik withdrew its routers** → `leaguesphere.app` returned the catch-all **404** for ~10 minutes.

Diagnosis was made by the concurrent session, which mitigated it live with
`docker network disconnect proxy moodle.app`. That mitigation was temporary by construction: the next
`docker compose up` re-attaches the container and re-breaks LeagueSphere.

## Fix

Renamed the compose service `app` → **`moodle`** (container `moodle.moodle`), which makes the alias
unique on the shared network.

Deliberately **not** `web`, which was the obvious first suggestion: `web` is already a shared alias in
this repo (`bnb-office.web`, `dontforget.web`), so it is the same hazard one incident away. Any future
proxy-attached service in this repo should claim a name nothing else resolves; the checklist is now in
[moodle/AGENTS.md](../moodle/AGENTS.md).

Cost of the fix: the rename leaves the old container as an **orphan**, and `docker compose images`
then fails on the dangling image reference, which aborts the Ansible deploy *before* it can create the
new service. So the old container has to be removed first:

```bash
ssh lehel.xyz "docker rm -f moodle.app"     # orphan from the rename; do this once
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.moodle
```

This is the `manage-service` skill's "orphaned containers" pitfall.

## Verified

| Check | Result |
|---|---|
| `app` resolves from a proxy peer | `172.25.0.6` — LeagueSphere's own backend, single answer |
| `moodle` resolves from a proxy peer | `172.18.0.4` — the Moodle app |
| leaguesphere.app | `200 LeagueSphere` |
| m.leaguesphere.app/offd/moodle/ | `200 Home \| offd`, login form `200` |
| After `compose up -d --force-recreate moodle` | still `200` both, `app` unchanged — the regression test that matters |
| Container-health probe | `system_container_running{moodle.moodle,moodle.db,moodle.cron} = 1` |

## Also caught while fixing

The service had never been registered in the two lists the `manage-service` checklist requires:

- `ansible/plays/vars/secrets.yml` → `docker.services[]` — drives the container-health probe, Pi-hole
  `dns.yml`, `test_host.sh` and the test host's `/etc/hosts`.
- `ansible/plays/roles/user/tasks/docker_extras.yml` → `forall_docker_services.sh`.

`host_ping` also gained optional per-entry `host`, because Moodle answers at `m.leaguesphere.app` and
the derived `moodle.lehel.xyz` has no router — it would have printed `[DOWN]` forever. Entries without
`host` keep the old derived name, so nothing else changed.

## Lesson worth carrying

A service name is not local to its compose file: on a shared network it is a **global DNS name**. The
generic ones (`app`, `web`, `api`, `db`) are all landmines; the failure is intermittent, cross-service,
and looks like an unrelated outage (404 on someone else's product).
