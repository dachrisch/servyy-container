# 2026-10-08 — Server skills canonical in setup-home, obra task kept

## Goal (user directive)

All skills canonical in the home repo (`setup-home/agent-config/`), deployed
from there; genuine server skills in their own `skills/server/` subdir.
Server keeps fetching superpowers from upstream (obra task stays — it is the
freshness mechanism, not duplication).

## Container-side changes

- `opencode` role (`tasks/main.yml`, `defaults/main.yml`): skill deploy `src`
  switched from `opencode/skills/` to setup-home canonical on the controller
  (`agent_config_skills_src`, default
  `~/dev/infrastructure/setup-home/agent-config/skills`; `copy` already runs
  controller-side, so servers need no new git access). Explicit shared list
  (`opencode_server_shared_skills: gh-stack, release-please`) + full
  `server/` contents preserve the flat dest layout the plugin and skill
  discovery require. Bulk-copy replaced on purpose: a shared dir must never
  leak dev-only skills onto the server.
- Deleted vendored/moved `opencode/skills/{gh-stack,release-please,
  opencode-deployment,opencode-contribution,opencode-dependency,
  docstash-artifacts,session-messaging}/` (now canonical in setup-home;
  `opencode/skills/` dir is gone).
- `opencode/SKILLS.md` rewritten as pointer (canonical location, refresh
  procedures, layout rule).
- Untouched by design: obra/superpowers clone + pin (`06b92f3…` — the single
  shared pin, also read live by setup-home), plugins, `opencode.json.template`,
  `tui.json`, `startup.sh` (§3b gh-extension stays), gh-wrapper, `.ssh`, `.env`.

## Verification (test-first)

- `servyy.yml --syntax-check -i testing` clean.
- `servyy-test.sh --tags user.docker.opencode`: ok=52 failed=0; all 21 skill
  dirs land, every file md5-verified against canonical (shared) and the obra
  pin (superpowers); container healthy (in-container `/health` → 401 as the
  healthcheck expects; host-direct curl never worked — no published ports,
  same as before).
- Prod `codey.lehel.xyz`: ok=53 failed=0; 21 dirs, key skills present,
  `/health` → 401 in-container. Restart was notify-driven, as with any
  skills change.

## Notes

- A `find … excludes: server` subtlety and the controller-side `src` default
  were both verified live; molecule has no opencode-role dir (docker_service
  molecule unaffected — only `opencode.env` assertions there).
- In-skill path references to the old `opencode/skills/` source were updated
  in the canonical copies (setup-home side); deployed layout is byte-identical
  to before, so the server cannot tell the difference.
