# Global instructions (codey.lehel.xyz)

This OpenCode server runs as the container `opencode.web` on `codey.lehel.xyz`
and is reachable at https://code.lehel.xyz behind Basic auth (Caddy authgate,
plus opencode's own `OPENCODE_SERVER_PASSWORD`).

Source of truth for this file is `opencode/scripts/AGENTS.md` in the
`infrastructure/container` repo. `startup.sh` re-copies it into
`/root/.config/opencode/AGENTS.md` on every boot, so edits made inside the
container are overwritten on restart — change the repo file and deploy it.

- Shared checkouts live under `/root/dev` (volume `codey_dev_checkouts`, also
  referenced by the production-disabled `claude-hub` service). Repos there carry
  their own `AGENTS.md`; read those before changing code.
- Infrastructure changes go through the `infrastructure/container` repo and
  Ansible (`cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags <tag>`).
  Never make manual changes on the host.
- You run *inside* the container: there is no docker CLI and no docker socket,
  so `docker ps` / `docker exec` / `docker logs` fail here. Check this server
  over loopback instead:
  `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4096/health`
  (expect `200`).
- Host-level checks need SSH to the host this container runs on — prefix them
  with `ssh codey.lehel.xyz "…"`, e.g.
  `ssh codey.lehel.xyz "docker logs portainer.ofelia"` (Ofelia's prune output).
- Session data lives in `/root/.local/share/opencode/opencode.db`; pruning runs
  nightly at 04:00 via Ofelia.
- Plugin-local tools: `session_list` / `session_send` reach other OpenCode
  sessions on this host; MCP servers `circleci`, `chrome-devtools` (headless
  chromium) and `docstash` are available.
