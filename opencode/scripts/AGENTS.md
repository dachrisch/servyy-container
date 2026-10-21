# Global instructions (codey.lehel.xyz)

This OpenCode server runs as the container `opencode.web` on `codey.lehel.xyz`
and is reachable at https://code.lehel.xyz behind Basic auth (Caddy authgate,
plus opencode's own `OPENCODE_SERVER_PASSWORD`).

- Shared checkouts live under `/root/dev` (volume `codey_dev_checkouts`, also
  referenced by the production-disabled `claude-hub` service). Repos there carry
  their own `AGENTS.md`; read those before changing code.
- Infrastructure changes go through the `infrastructure/container` repo and
  Ansible (`cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags <tag>`).
  Never make manual changes on the host.
- Verify the server with `docker ps --filter name=opencode.web` and, because
  port 4096 is not published on the host,
  `docker exec opencode.web sh -c 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4096/health'`
  (expect 200).
- Session data lives in `/root/.local/share/opencode/opencode.db`; pruning runs
  nightly at 04:00 via Ofelia (logs: `docker logs portainer.ofelia`).
- Plugin-local tools: `session_list` / `session_send` reach other OpenCode
  sessions on this host; MCP servers `circleci`, `chrome-devtools` (headless
  chromium) and `docstash` are available.
