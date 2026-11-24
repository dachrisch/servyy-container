# opencode/ — OpenCode server on codey.lehel.xyz

Reachable at https://code.lehel.xyz behind Basic auth (Caddy authgate plus OpenCode's
own server password). This directory holds the service definition, plugins, tests and
`scripts/`. **The global instructions for the server are not here** — their source of
truth is [`scripts/AGENTS.md`](scripts/AGENTS.md), copied by `startup.sh` into
`/root/.config/opencode/AGENTS.md` on every boot. Edit that file, not the container copy.

## Service-to-Service SSH (OpenCode Access)

The OpenCode role automatically:
1. Generates `id_servy` SSH key for accessing lehel.xyz
2. Mounts the private key in opencode containers
3. Adds the public key to lehel.xyz's authorized_keys (Docker network restricted)
4. Adds lehel.xyz to known_hosts to avoid SSH prompts

**Testing cross-server access:**

```bash
# Verify opencode container can reach lehel
ssh code.lehel.xyz "docker exec opencode.opencode ssh -i /root/.ssh/id_servy cda@lehel.xyz whoami"

# Should return: cda
```

**Access rights:**
- ✅ OpenCode SSH key authorized on lehel.xyz
- ✅ Restricted to Docker network ranges (security)
- ✅ No password needed (key-based only)
- ✅ Automatic lehel.xyz fingerprint in known_hosts

## Deploy order

opencode must be deployed before `claude-hub`: it creates the `codey_dev_checkouts`
named volume that claude-hub consumes with `external: true`.

## Reference

- [`scripts/AGENTS.md`](scripts/AGENTS.md) — global instructions deployed into the container.
- [Root AGENTS.md](../AGENTS.md) — deployment rules, SSH bootstrap and Key Services table.
- `history/2026-10-22_opencode-v2-upgrade.md`, `history/2026-11-13_opencode-container-bash.md`.
