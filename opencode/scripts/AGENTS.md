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
- **graphify writes into whatever tree it scans.** `graphify-out/` (graph.json,
  graph.html, GRAPH_REPORT.md) lands in the scanned directory — for a repo under
  `/root/dev` that directory is shared with claude-hub, so `graphify-out/` is
  pre-seeded in git's global excludes (`/root/.config/git/ignore`, written by
  `startup.sh` §3c). Keep it out of commits; build graphs from a scratch copy
  when a scan would otherwise pollute a checkout mid-task.
- **git-crypt checkouts under `/root/dev`.** git-crypt state lives in
  `<repo>/.git/git-crypt/keys/` — `./.git-crypt/` is a different thing (it is
  only the GPG-escrow dir), so an empty `.git-crypt/` does *not* mean locked;
  that misprobe caused a false "repo is locked" diagnosis on 2026-11-10
  (`history/2026-11-10_opencode-gitcrypt-provision-repair.md`). The key itself
  comes from `GIT_CRYPT_KEY_B64` and is installed by `provision-dev.sh`.
  - Diagnose before concluding: `git config --local --get filter.git-crypt.smudge`
    (must be the git-crypt command, not `cat`) and
    `git-crypt status -e | head`.
  - Secrets reading as `\0GITCRYPT\0` usually means the *working tree* holds
    ciphertext, not that the repo is locked: run `git-crypt unlock "$KEYFILE"`
    (or just restart the container, which re-provisions) instead of editing
    files or hand-writing git config.
  - **Never** run git with `-c filter.git-crypt.smudge=cat -c filter.git-crypt.clean=cat`.
    It writes ciphertext blobs into the working tree and leaves the checkout
    silently half-decrypted. If a binary merge forces it (encrypted YAML such as
    `traefik/*.yaml` cannot be merged), re-run `git-crypt unlock` in that
    checkout afterwards.
  - If `provision-dev.sh` logs `update failed` and `git status` shows an
    encrypted file as modified while its working-tree content already looks
    correct, check the blob: a file whose ciphertext blob is **22 bytes** is the
    encryption of an *empty* file, and git-crypt cannot re-encrypt it back to
    that blob (`clean` of empty input emits 0 bytes), so the path is modified
    forever and blocks `checkout`/`pull`. Filter overrides do not help — git's
    up-to-date check is stat/size based. Remedy: `git reset --hard origin/master`
    in that checkout, and get the empty file deleted upstream (CI's
    `validate-git-crypt.sh` now rejects that shape).
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
- **No SSH daemon in this container.** The image ships no OpenSSH; `startup.sh`
  installs `openssh-client-default` (ssh/scp/sftp/ssh-keygen) and never the
  `openssh` meta, which would pull `openssh-server`. That matters because
  Alpine/musl without PAM is the vulnerable combination in the 2026 "sshole"
  musl OpenSSH auth bypass. Do not `apk add openssh` or start an sshd — nothing
  here binds `:22`, and a server is a liability, not a feature.
- Plugin-local tools: `session_list` / `session_send` reach other OpenCode
  sessions on this host; MCP servers `circleci`, `chrome-devtools` (headless
  chromium) and `docstash` are available.
