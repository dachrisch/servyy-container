# architecture/ — the service landscape map

A machine-readable map of what runs where, plus the renderer that keeps it honest.
The high-level request path is described in the [root AGENTS.md](../AGENTS.md); this
directory is the detailed, checked version.

## Source of truth

`landscape.yaml` is the single source of truth for the architecture view. It is
**git-crypt encrypted** (the `*.yaml` rule) because it names internal hosts, tiers and
service internals while this repository is public. Curated fields (name, group, notes,
calls, externals, invariants) are human judgement; mechanical fields (containers,
domains, images, tier servers and every dependency edge) are derived from the repo and
compared with running containers.

## render.py

`render.py` is the only reader. Its modes:

| Mode | Effect |
|---|---|
| `--verify` | Diff the map against compose files and `db_tenants.yml`; non-zero on drift. This is the point of keeping a map at all. |
| `--build` | Print mechanical fields as YAML to paste back into the map. Never rewrites the file — comments are curated content. |
| `--html` | Render the self-contained DocStash HTML page from the map alone. |
| `--selftest` | Parse the repository and assert the derivation still works. CI runs this because CI has no git-crypt key. |

```bash
python3 architecture/render.py --verify
python3 architecture/render.py --build
python3 architecture/render.py --html > /tmp/architecture.html
python3 architecture/render.py --selftest
```

`render.py` needs PyYAML; the Ansible interpreter has it.

## Rules

- Answer "what runs where", "what depends on X", "which domain maps to which service" or
  "which database does an app use" from the map — never from memory.
- If `--verify` reports drift, fix the map or the repository in the same change; do not
  paper over it by editing curated fields.
- A new service or tenant means a map update, then `--verify` before committing.
- The `servy-landscape` skill is the workflow wrapper around these commands.
