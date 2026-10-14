# 2026-10-14 — session-messaging skill + plugin: canonical source moved to setup-home

## Goal (user directive)

The `session-messaging` skill and its opencode plugin were effectively
server-only. Make them available on dev machines too, with one owner.

## What moved where

- `session-messaging` **skill**: promoted from setup-home
  `agent-config/skills/server/` to the shared level
  `agent-config/skills/session-messaging/`. The container role now ships it via
  `opencode_server_shared_skills` (added) instead of the server-only loop
  (removed); setup-home fans it into dev homes.
- `session-messaging` **plugin**: canonical copy now lives in setup-home
  `agent-config/plugins/session-messaging.js`. The container copy
  `opencode/plugins/session-messaging.js` is **deleted**.
  - New default `agent_config_plugins_src` points at the setup-home plugins
    dir; the role gains a task that copies `session-messaging.js` to the server
    plugins dir (`~/servyy-container/opencode/plugins/`, bind-mounted to
    `/root/.config/opencode/plugins`).
  - `opencode/plugins/superpowers.js` stays container-owned (it is the server
    patch tied to `opencode_superpowers_version`); the "Deploy OpenCode plugins"
    task still ships it.

## Files

- `ansible/plays/roles/opencode/defaults/main.yml` — `agent_config_plugins_src`
  added; `session-messaging` added to `opencode_server_shared_skills`.
- `ansible/plays/roles/opencode/tasks/main.yml` — server-only skill loop loses
  `session-messaging`; new "Deploy session-messaging plugin" task.
- `opencode/plugins/session-messaging.js` — deleted.
- `opencode/SKILLS.md` — documented the shared skill + setup-home plugin source.

## Verification

- `ansible-playbook servyy.yml --syntax-check -i testing` — pass.
- `yamllint` on the changed role files — clean.
- Deploy to servyy-test via `--tags user.docker.opencode` on the next test pass.

Paired change: setup-home
`history/2026-10-14_session-messaging-shared-skill-and-plugin.md`.

## Follow-up

Enabling it on a dev machine surfaced two fixes (both in the setup-home
canonical plugin / role, redeployed here): the plugin's helper functions are no
longer exported (OpenCode treats every export as a plugin factory and they
threw), and setup-home installs plugins as copies rather than symlinks (a
symlink broke `@opencode-ai/plugin` resolution). Server confirmed export-clean
after redeploy.
