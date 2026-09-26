# OpenCode server skills

This directory is the source of truth for skills on the opencode server
(`codey.lehel.xyz`). Ansible copies it to
`~/servyy-container/opencode/skills/`, which is bind-mounted read-only to
`/root/.config/opencode/skills` (see `docker-compose.yml`).

## Owned skills (edit freely)

- `docstash-artifacts/` — DocStash MCP workflow (MCP endpoint is configured
  in `scripts/opencode.json.template`; no plugin needed).
- `opencode-contribution/`, `opencode-dependency/`, `opencode-deployment/`
- `release-please/` — release-please workflows (single `SKILL.md`, no deps).

## Vendored skills (do NOT hand-edit, refresh from upstream)

- `gh-stack/` — snapshot of `github.com/github/gh-stack`, path
  `skills/gh-stack`, `refs/tags/v0.1.0` (provenance in frontmatter).
  Runtime dep: the `gh-stack` gh-CLI extension, auto-installed by
  `scripts/startup.sh` (§3b). Refresh: copy `SKILL.md` from a newer
  tag and keep the frontmatter provenance current.
- `brainstorming/`, `dispatching-parallel-agents/`, `executing-plans/`,
  `finishing-a-development-branch/`, `receiving-code-review/`,
  `requesting-code-review/`, `subagent-driven-development/`,
  `systematic-debugging/`, `test-driven-development/`,
  `using-git-worktrees/`, `using-superpowers/`,
  `verification-before-completion/`, `writing-plans/`, `writing-skills/`
  — deployed **live from upstream**, not stored here. Ansible clones
  `https://github.com/obra/superpowers.git` at the pinned commit
  (`opencode_superpowers_version` in
  `ansible/plays/roles/opencode/defaults/main.yml`, currently
  `06b92f36` / 2026-01-30) to controller `/tmp` and copies `skills/`
  contents flat into the server skills dir. Refresh: bump the pin,
  redeploy, and re-check the SERVER PATCH in
  `plugins/superpowers.js` still applies.

Layout rule (per https://opencode.ai/docs/skills/): one folder per skill,
folder name == frontmatter `name`, all flat — no nesting, and NO loose
`.md` files directly in `skills/` (this fork registers those as skills
too — a stray README would show up in the registry). The matching
bootstrap plugin lives in `plugins/` (auto-loaded from
`/root/.config/opencode/plugins/`, see https://opencode.ai/docs/plugins/).
