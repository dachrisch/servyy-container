# Remove graphify — remaining work (container repo + codey server)

Status 2026-11-19: **local, setup-home and leaguesphere are done and pushed.**

- setup-home `81b799d` (`chore(agent-config): retire graphify`) — pushed to
  `git.lehel.xyz/home.git`.
- leaguesphere `dc4ec9a02` (`chore: remove graphify tooling and its
  graph-derived module map`) — pushed to `github.com:dachrisch/leaguesphere`.
- Local machine: CLI uninstalled, cache/plugin/skill links/backup/output trees
  removed. Only `agent-config/skills/graphify/` and
  `container/graphify-out/` remain on disk.

Deferred because `/home/cda/dev/infrastructure/container` (servyy-container) is
busy with other work. **Do not start until that tree is quiet and nothing is
mid-deploy** — this plan edits it, recreates the `opencode.web` container and
deletes 143.7 MB from its persistent volume.

## Ordering constraint

`setup-home/agent-config/skills/graphify/` is the `copy` source for
`opencode_server_shared_skills`. Deleting it before removing `graphify` from
that list makes the next `user.docker.opencode` run fail with a missing source.
Steps 1 and 2 must land together (same session, before any deploy).

---

## Step 1 — servyy-container config edits

Root: `/home/cda/dev/infrastructure/container`

### 1.1 `ansible/plays/roles/opencode/defaults/main.yml`

Remove the entry and add a retired list next to it:

```yaml
opencode_server_shared_skills:
  - adding-opencode-bot
  - gh-stack
  - release-please
  - session-messaging
# Skills dropped from opencode_server_shared_skills; the server copies are not
# pruned by the copy tasks, so delete them explicitly on the next deploy.
opencode_server_retired_skills:
  - graphify
```

### 1.2 `ansible/plays/roles/opencode/tasks/main.yml`

Add after “Deploy shared canonical skills to OpenCode server”:

```yaml
- name: Remove retired shared skills from OpenCode server
  ansible.builtin.file:
    path: "{{ (opencode_skills_dir, item) | path_join }}"
    state: absent
  loop: "{{ opencode_server_retired_skills }}"
  vars:
    opencode_skills_dir: "{{ ('/home/', create_user, 'servyy-container/opencode/skills') | path_join }}"
  notify: restart opencode container
  tags: [user.docker.opencode]
```

### 1.3 `opencode/scripts/startup.sh` — delete three blocks

| Lines | Block |
|---|---|
| 122–160 | `# 3c. graphify CLI (required by the graphify skill).` — the whole install/else/background block |
| 162–173 | `# The CLI floats (…)` — version-drift warning comparing CLI vs `.graphify_version` |
| 175–181 | `# graphify writes graphify-out/ (…)` — the `gitignore_global` seeding block |

Keep `# 4. Configuration Substitution` and everything after it. Renumber
nothing else (there is no §3d).

### 1.4 `opencode/scripts/install-graphify.sh`

Delete the file.

### 1.5 `opencode/docker-compose.yml`

Remove the comment block at lines 24–31 plus `PYTHONPATH: /root/.graphify-pkgs`
(line 32). `PYTHONPATH` has no other user.

### 1.6 `opencode/SKILLS.md`

Delete the `graphify/` bullet (lines 37–46, ends with “shipped
`.graphify_version` disagree.”).

### 1.7 `opencode/scripts/AGENTS.md`

Delete the bullet at lines 15–20 (“**graphify writes into whatever tree it
scans.** …”).

### 1.8 `.gitignore`

Delete lines 51–52 (`# graphify skill output …` + `graphify-out/`).

### 1.9 `docs/plans/2026-11-17-opencode-derived-image.md`

Strip graphify: requirement bullets (lines 42–52), the table row (line 64), the
build step comment + `COPY`/`RUN` block (lines 115–130), the verification lines
(195–201, 210–213), and the manual checks (439–442). The plan is then a derived
image without graphify — text otherwise unchanged.

### 1.10 `graphify-out/`

`rm -rf graphify-out` (untracked, 11 MB).

---

## Step 2 — setup-home finish

1. Delete `agent-config/skills/graphify/` (SKILL.md, `references/`,
   `.graphify_version`).
2. Run `ansible-playbook ansible/home.yml --check --tags user.agent_config`,
   then without `--check`. This prunes the `graphify.js` plugin copy (already
   listed in the retired-plugin loop) and removes any dangling skill links.
3. Expect `changed` only for that plugin and no graphify link in
   `~/.claude/skills`, `~/.config/opencode/skills`, `~/.qwen/skills`.

---

## Step 3 — deploy to codey.lehel.xyz

From `container/ansible`:

```bash
./servyy.sh --check --limit codey.lehel.xyz --tags user.docker.opencode
./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
```

The role notifies `restart opencode container`; expect one recreate (boot cost
drops by roughly the graphify install time — ~0 s now that the block is gone).

## Step 4 — persistent-volume and container cleanup

```bash
ssh codey.lehel.xyz 'sudo docker exec opencode.web rm -rf /root/.graphify-pkgs'
ssh codey.lehel.xyz "sudo docker exec opencode.web sh -lc '
  sed -i \"/^graphify-out\\/$/d\" /root/.config/git/ignore
  cat /root/.config/git/ignore'"
```

`/root/.graphify-pkgs` is 143.7 MB on volume `opencode_opencode_root`; nothing
else reads it once `PYTHONPATH` is gone. The gitignore line is a leftover the
old `startup.sh` appended on every boot — removing it does not affect other
entries (verify nothing else was in the file before deleting it blindly).

## Step 5 — verification

```bash
# server: no CLI, no import, no skill, no leftovers
ssh codey.lehel.xyz 'sudo docker exec opencode.web sh -lc "
  command -v graphify; command -v graphify-mcp;
  python3 -c \"import graphify\" 2>&1 | tail -1;
  ls /root/.config/opencode/skills | grep -i graphify;
  ls -d /root/.graphify-pkgs 2>&1"'

# host copy of the shared skills
ssh codey.lehel.xyz 'ls /home/cda/servyy-container/opencode/skills | grep -i graphify'

# startup log and health
ssh codey.lehel.xyz 'sudo docker logs --since 10m opencode.web 2>&1 | grep -i graphify'
ssh codey.lehel.xyz 'sudo docker inspect -f "{{.State.Health.Status}}" opencode.web'
```

Expected: empty outputs for the first three (only “No module named graphify”
from the import), no log lines, `healthy` — plus the usual
`inside_health=200` / `inside_info=401` style check if the deploy script
reports it.

## Step 6 — history amendments (container repo)

Append to `history/2026-11-11_graphify-skill-and-cli.md`:

```markdown
## Update 2026-11-19 — retired: no benefit
graphify gave no benefit over plain search in practice. Removed everywhere:
the shared-skills entry and the server copy, `startup.sh` §3c plus the drift
warning and `graphify-out/` gitignore seeding, `scripts/install-graphify.sh`,
`PYTHONPATH` in `docker-compose.yml`, `/root/.graphify-pkgs` (143.7 MB, freed),
and the container's `graphify-out/` global-gitignore line. setup-home's
canonical skill tree and history entry were updated in `81b799d`.
```

Add one line to the graphify paragraphs of
`history/2026-11-17_opencode-boot-cost.md` and
`history/2026-11-17_oracle-codey-replication.md`: “Obsolete 2026-11-19 —
graphify removed as unused; the rest of this record still applies.”

## Step 7 — commit and push

```bash
cd /home/cda/dev/infrastructure/container
git status --porcelain           # expect ONLY the files above
git add ansible/plays/roles/opencode/ opencode/ .gitignore \
        docs/plans/2026-11-17-opencode-derived-image.md history/
git commit -m "chore(opencode): retire graphify"
git push origin master
```

Do not stage anything else from that tree — it is expected to hold unrelated
in-flight work.

---

## Rollback

- Config: `git revert` the commits (container + setup-home). The role is
  idempotent, so a redeploy restores the file state; graphify itself would need
  `python3 -m pip install graphifyy` (aarch64 needs
  `install-graphify.sh`, now deleted — recoverable from git history).
- Deleted outputs (`graphify-out/`, `/root/.graphify-pkgs`) are generated, not
  restored.
- Container restart is the only production-visible effect.

## Notes

- `graphify` was invoked on aarch64 via `PYTHONPATH=/root/.graphify-pkgs`, so
  there is no `/usr/bin/graphify` to remove on codey; on x86 hosts the pip
  install lands in the image rootfs and disappears on recreate anyway.
- No molecule test, CI job or other role references graphify (checked
  2026-11-19), so no test updates are needed.
