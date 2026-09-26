# Ship gh-stack + superpowers + release-please skills to opencode server

## Problem
The opencode server (`codey.lehel.xyz`) only shipped 4 owned skills. Three more
were in use on the workstation but missing on the server: `gh-stack` and the 14
`superpowers` skills (both upstream, not owned) and `release-please` (owned,
existed only in `~/.config/opencode/skills/`).

## Solution
- Vendored `opencode/skills/gh-stack/SKILL.md` (upstream
  `github/gh-stack@v0.1.0`, provenance in frontmatter) and
  `opencode/skills/release-please/SKILL.md` (byte-exact copies).
- Superpowers skills deploy live from upstream: Ansible clones
  `obra/superpowers` at the pinned SHA in
  `opencode_superpowers_version` (currently `06b92f36`, 2026-01-30) to
  controller `/tmp` and copies `skills/` contents FLAT into the server
  skills dir (documented discovery: `skills/<name>/SKILL.md`). No repo
  submodule (npm `superpowers` is an unrelated squatter placeholder, so no
  one-line plugin install exists).
- New `opencode/plugins/superpowers.js`: upstream file plus a 2-line server
  patch (`'../../skills'`→`'../skills'`; message path
  `skills/superpowers/`→`skills/`) with provenance header describing how to
  re-apply on refresh. The patch is unavoidable: the plugin locates its
  bootstrap relative to `__dirname`, which only holds inside the clone.
- New `./plugins:/root/.config/opencode/plugins:ro` compose mount (file
  plugins auto-load from there) + Ansible plugins deploy tasks with restart
  notify (also added the missing notify to the existing skills task).
- `startup.sh` §3b installs the `gh-stack` gh-CLI extension idempotently at
  boot (persists via `opencode_root` volume) + global `rerere`/`pushDefault`
  git config from the skill prerequisites. Never fails the boot.
- DocStash needs nothing: MCP endpoint + `docstash-artifacts` skill already
  ship; no DocStash opencode plugin exists.
- `opencode/skills/README.md` records provenance + refresh procedure.

## Files changed
`opencode/skills/{gh-stack,release-please}/SKILL.md` (new),
`opencode/skills/README.md` (new), `opencode/plugins/superpowers.js` (new),
`opencode/docker-compose.yml`, `opencode/scripts/startup.sh`,
`ansible/plays/roles/opencode/{tasks,defaults}/main.yml`.

## Live verification in container (servyy-test.lxd, hard-reset fresh box)
- `GET /api/skill` on the running `opencode.web` returns the registry:
  first pass caught TWO bugs — (1) `release-please` never loads anywhere
  (its SKILL.md has NO frontmatter; `name`+`description` are required),
  fixed by adding frontmatter in-repo (also still broken on the laptop's
  `~/.config` copy); (2) this fork registers loose `skills/*.md` too, so
  `skills/README.md` showed up as skill "README" — moved to
  `opencode/SKILLS.md` (also documents the no-loose-md rule).
- After fix + recreate: registry = 21 entries (20 dirs + builtin
  `customize-opencode`), README gone, `release-please` present, all 14
  superpowers + `gh-stack` + `docstash-artifacts` locations point at
  `/root/.config/opencode/skills/*/SKILL.md` (bind mounts land).
- Plugin hook proven functionally: imported the vendored file under a
  container-identical layout in node — `experimental.chat.system.transform`
  injects the full `using-superpowers` body verbatim with the flat
  `skills/` path (prompt-time LLM run not possible on test: no provider
  keys by design).
- `startup.sh` §3b proven live: `gh-stack extension installed` on a
  PAT-less box via the `gh.real` unauthenticated fallback (first version
  failed because the `gh` wrapper hard-fails with no PAT — fixed).
- Container `unhealthy` on test is expected: healthcheck greps for 401
  but test has no server password configured (pre-existing, prod has auth).

## Verification (test-first)
- Local: `sh -n`, `node --check`, compose YAML parse, `yamllint`,
  `ansible-playbook plays/user.yml --syntax-check -i testing`,
  `ansible-lint plays/roles/opencode/` — all green.
- `servyy-test.lxd` hard-reset (old box had a 13-day wedged
  unattended-upgrade + broken libc deps), then
  `ansible-playbook servyy.yml -i testing --tags user.docker.opencode`:
  all opencode tasks green; deployed 20 skill dirs + README + patched
  plugin verified on the box (incl. `using-superpowers` bootstrap,
  exact line counts).
- Known pre-existing test-env gaps (not this change): full play stops at
  servyy-container clone because the controller checkout sits on local
  branch `claude/claude-hub-june-hub-merge`, which no longer exists on
  origin; container restart handler needs docker.sock access on test.
  Runtime check (plugin load log, `gh extension` at boot) still open —
  needs a running opencode container on test.

## Deployment
NOT yet deployed to prod `codey.lehel.xyz`. Next: run test handler path,
then `ansible/servyy.sh --limit codey.lehel.xyz` (or standard prod flow).
