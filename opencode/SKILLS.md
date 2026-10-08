# OpenCode server skills — canonical source moved

Skills for the opencode server (`codey.lehel.xyz`) are canonical in the
**setup-home** repo (private `home.git`):
`agent-config/skills/` — shared skills at the top level,
server-runtime skills in `skills/server/`.

The `opencode` Ansible role copies controller-side from that checkout
(`agent_config_skills_src`, default
`~/dev/infrastructure/setup-home/agent-config/skills`) to
`~/servyy-container/opencode/skills/`, which is bind-mounted read-only to
`/root/.config/opencode/skills` (see `docker-compose.yml`). Server ships an
explicit list (`opencode_server_shared_skills` + full `server/` contents);
superpowers still deploys live from upstream at `opencode_superpowers_version`
(that pin is shared with setup-home — never duplicate it).

Refresh procedures (edit canonical, then redeploy
`--tags user.docker.opencode` after servyy-test):
- Owned/server skills: edit in setup-home `agent-config/skills/server/`.
- `release-please/`: single copy owned in setup-home canonical (absorbed
  this directory's copy including its frontmatter fix) — edit there.
- `gh-stack/`: upstream snapshot (`github/gh-stack` tag `v0.1.0`) — copy
  `SKILL.md` from a newer tag into the setup-home copy, keep its frontmatter
  provenance current. Runtime dep unchanged: the `gh-stack` gh-CLI extension,
  auto-installed by `scripts/startup.sh` (§3b).
- `superpowers/`: bump `opencode_superpowers_version` in
  `ansible/plays/roles/opencode/defaults/main.yml`, redeploy, re-check the
  SERVER PATCH in `plugins/superpowers.js` still applies. Setup-home follows
  the same pin automatically.

Layout rule (per https://opencode.ai/docs/skills/): one folder per skill,
folder name == frontmatter `name`, all flat — no nesting, and NO loose
`.md` files directly in the deployed skills dir (this fork registers those
as skills too — a stray README would show up in the registry). The matching
bootstrap plugin lives in `plugins/` (auto-loaded from
`/root/.config/opencode/plugins/`, see https://opencode.ai/docs/plugins/).
