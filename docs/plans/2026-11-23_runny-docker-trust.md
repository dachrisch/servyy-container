# CI runners without root — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **Revision 2026-11-23e: agreed ready to implement** by this session and opencode session
> `ses_dfb9efd14ffeJnwhbuq4etWaD8`. rev e changes: root-run Docker is masked first in rootless.yml,
> because the node-exporter package needs `:9100` free; no manual `compose down` or `gpasswd` on any
> host, since both moved into Ansible; and the AppArmor check `grep -qx 'rootlesskit (unconfined)'`
> was confirmed on runny (rc 0).
> **Revision 2026-11-23d.** This revision simplifies rev c. runny is a runner host and nothing
> else, so it gets no runner container and leaves the shared Docker plays. One unprivileged user
> runs two systemd user services, rootless `dockerd` and the `forgejo-runner` binary, and the
> root-run daemon is masked. No dind, no compose project, no socket mapping, and no
> `docker_rootful` switches across the repo. Facts the plan relies on were checked on runny and in CI
> on 2026-11-23 (§1). Each task says when to stop and ask (**Stop if**).

**Goal:** On runny, the runner and every job run without root: no root-run daemon socket and no
`--privileged` container anywhere in the chain. Jobs still build images with
`docker/setup-buildx-action` + `docker/build-push-action`.

**Target shape (runny):**
```
runny.lehel.xyz                     root-run docker.service / docker.socket / containerd: MASKED
├─ prometheus-node-exporter         Ubuntu package, :9100, existing INPUT filter → servy only
└─ user runner                      nologin, no sudo, not in docker, subuid 296608:65536, lingering
   ├─ docker.service   (--user)     /usr/share/docker.io/contrib/dockerd-rootless.sh → %t/docker.sock
   ├─ forgejo-runner.service (--user)  /usr/local/bin/forgejo-runner daemon, DOCKER_HOST=%t/docker.sock
   ├─ docker-prune.timer (--user)   daily prune of the rootless daemon
   └─ job containers                get runner's socket = runner's rights, --memory=900m
```

**Tech Stack:** Forgejo 15.0.12 on servy (v17 on master, not deployed) · forgejo-runner 13.2.1
(static binary) · Ansible (`forgejo_runner` role gains a `rootless` backend; `system` role, one gate) ·
Ubuntu 26.04, kernel 7.0 · `docker.io` 29.1.3 · `rootlesskit` 2.0.2 · Oracle E2.1.Micro (2 threads,
951 MB).

**Scope:** runny only. codey keeps privileged dind (F6) until a follow-up plan (§9). servyy-test's
container-based runner is unchanged.

---

## 0. Acceptance criteria (definition of done)

Run after Task 5. "Job" = a step in `cda/energy.consumption`, branch `forgejo-diag`, `runs-on: amd64`.
`RUN=` is shorthand for `sudo -u runner XDG_RUNTIME_DIR=/run/user/$(id -u runner)`.

| # | Where | Check | Expected |
|---|---|---|---|
| 1 | host, as `cda` | `docker ps` | fails (no socket / permission denied) |
| 2 | host | `systemctl is-enabled docker.service docker.socket containerd.service` | `masked` ×3 |
| 3 | host | `$RUN systemctl --user is-active docker forgejo-runner` | `active` ×2 |
| 4 | job | `docker info --format '{{json .SecurityOptions}}'` | contains `name=rootless` |
| 5 | job | `docker run --rm --privileged alpine sh -c 'head -c16 /dev/sda; echo rc=$?'` | `Permission denied`, `rc=1` |
| 6 | job | `docker run --rm -v /:/host:ro alpine sh -c 'cat /host/etc/shadow; echo rc=$?'` | `Permission denied`, `rc=1` |
| 7 | job | `docker run --rm -v /:/host alpine sh -c 'touch /host/root/x; echo rc=$?'` | `rc=1` |
| 8 | job | `docker run --rm -v /home/cda:/c alpine ls /c` | `Permission denied` (`/home/cda` is `750`) |
| 9 | job | `docker run --rm --memory=900m alexeiled/stress-ng --vm 1 --vm-bytes 1200M --timeout 30s` | killed (OOM); `ssh runny.lehel.xyz uptime` answers throughout |
| 10 | host | `sysctl kernel.apparmor_restrict_unprivileged_userns` | `= 1` |
| 11 | job | `setup-buildx-action` + `build-push-action` (`push: false`) | image built |
| 12 | job | `setup-node` with `cache: npm`, run twice | second run: `Cache restored` |
| 13 | workstation | `nc -zv -w3 runny.lehel.xyz <cache port>` | refused / timeout (cache not internet-facing) |
| 14 | servy | Prometheus target `runny` (`runny.lehel.xyz:9100`) | `up` |

Not a check: `ls /host` listing the real host root. Host-level rootless sees the real filesystem,
and the boundary is file permissions (5–8), not the view (F7).

## 1. Verified state (2026-11-23)

- **Socket grant live:** `fc422ae3` (rebase of `d9809ae1`, which is on no branch) is on `origin/master`.
  runny `data/config.yml:46` → `docker_host: "unix:///var/run/docker.sock"`. **Any job on runny is
  root on runny until Task 0 ships.**
- **CI red for this role:** run `45062636987` failed `Molecule Test (forgejo_runner/default)` at
  *Verify the dind config hands the dind socket*. The template renders `docker_host: "…"` **quoted**,
  but `verify.yml:59,64` grep unquoted. Later master runs pass only because they're path-gated.
- **Docker on runny is Ubuntu's:** `docker.io 29.1.3-0ubuntu4.1`, installed on every host from
  `plays/vars/default.yml:19` (`sys_packages`). `docker-ce-rootless-extras` doesn't exist here. Available:
  `/usr/share/docker.io/contrib/dockerd-rootless.sh` (+ `-setuptool.sh`); apt: `rootlesskit 2.0.2`,
  `slirp4netns 1.3.3`, `passt`, `uidmap`.
- **AppArmor already handled by Ubuntu:** `/etc/apparmor.d/rootlesskit` is
  `profile rootlesskit /usr/bin/rootlesskit flags=(unconfined) { userns, … }`, and `slirp4netns` has one too.
  No custom profile, no sysctl change.
- **cgroup delegation already on:** `user@.service` → `Delegate=pids memory cpu`.
- **Free subuid range:** `296608:65536` (after `opc`, `ubuntu`, `cda`).
- **Memory baseline:** root-run `dockerd` 57 MB + `containerd` 20 MB RSS; `available` 495 MB at idle.
- **What `with_docker` / `with_containers` gate on runny** (both `true` today, both become `false`):
  - `roles/user/tasks/main.yml:95-99` → `docker_setup.yml` (`cda` → `docker`, network `proxy`,
    daemon.json). Skipped, which is what we want.
  - `roles/user/tasks/main.yml` (`docker_extras`, dns, host_ping, …) on `with_containers`. Skipped; runny runs no services.
  - `roles/system_probe/tasks/main.yml:154-211`: container-health probe. Its own cleanup task
    removes it when `with_containers` is false.
  - `roles/system/tasks/main.yml:55`: **`firewall.yml` is imported only `when: with_docker`**, and
    that file holds both the Docker edge filter and runny's node-exporter `:9100` filter
    (`firewall.yml:49-102`, gated on `forgejo_runner_node_exporter`). **This is the one gate that
    must change** (Task 4).
  - `roles/system/defaults/main.yml:10`: `fail2ban_web_tier_chain` falls back to `INPUT`. Fine;
    runny has `loki_blocklist_enabled: false`.
- **Cleanup:** `roles/system/tasks/main.yml:47` runs `docker_cleanup.yml` when
  `docker_cleanup.enabled` (`plays/vars/default.yml:150`, daily 02:00, `User=cda`, `docker system prune -a -f --volumes`).
- **References to the runner container:** `monitor/provisioning/alerting/alert-rules.yml:2958`
  (runner-offline description says `docker ps | grep runny.runner`) and
  `.claude/skills/check-server-status/SKILL.md`.
- Probe host state is clean: only `runny.runner` + `runny.node-exporter`; sysctl `1`.
- `origin/master` is moving (other sessions pushed today), so work on a branch.

## 2. Benchmarks (probe, unchanged)

| | GitHub `ubuntu-latest` | codey (arm64, dind) | runny (amd64, host socket) |
|---|---|---|---|
| node job wall | **36 s** | **103 s** | **966 s — failed** |
| `npm ci` cold / warm | ~12 s | 29 s / – | 160 s / 233 s |
| `test` (vitest) | 10 s | 31 s | **402 s, 5 failed** (mongodb-memory-server 10 s hook timeout) |
| docker build cold / warm | 69–111 s | 86 s / 13 s warm; stock `build-push-action` 172 s | **374 s / 109 s** |

Logs: `ssh servy.lehel.xyz 'docker exec ci.forgejo cat /var/lib/gitea/actions_log/cda/energy.consumption/<hex>/<id>.log.zst' | zstd -dc`

## 3. Findings (condensed)

- **F1 CPU is runny's wall:** 79 % steal, load1 12.25, 147 MiB free, 881 MiB swap; job cgroup peaked ~360/900 MB.
- **F2 cache unreachable:** today the runner's cache listens on its compose-network IP, which job
  bridges can't reach. **With the runner on the host this changes.** It listens on a host
  address, and rootless job containers reach host addresses through slirp4netns. Verified in Task 3 (#12),
  together with the cache port **not** being internet-facing (#13).
- **F3 servy bans runny:** `get_traefik_crawler_ips` (200 req / 2 min) in
  `roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2` counts the 2 s poll. That
  caused three IPv4 bans during the probe, and jobs hung "running".
- **F4 "stock workflows":** `.github/workflows` + `workflow_call` run. Actions must exist on
  `data.forgejo.org` (no github.com fallback). buildx/build-push work, and `type=gha` misses without failing.
  `actions/upload-artifact@v4+` fails (`not supported on GHES`), and the fix is the Forgejo fork
  `https://data.forgejo.org/forgejo/upload-artifact` or `@v3`. Re-check on v17.
- **F5 root socket = host root (live):** run 9 mounted `/`, read `data/.runner`, saw every container, escaped the cap.
- **F6 privileged dind = host root (codey's model):** a job-created `--privileged` container in a
  privileged dind read the host `/dev/sda` boot sector. Demonstrated read-only on runny.
- **F7 host-level rootless:** no privileged container anywhere. It sees the real filesystem with
  root-owned files as `nobody`, so jobs can read world-readable host files. Mitigation: `/home/cda`
  is `750`; the runner's files live under `runner` with `.runner` `0600`.

## 4. Decision

**Rootless Docker plus the forgejo-runner binary, both as systemd user services of `runner`.**
**Revoking the job socket** (Task 0) ships first as the stop-gap.

Rejected: dind and rootless-dind sidecars (privileged in the chain, F6/F7); rev c's runner
container on the rootless daemon (socket mapping, compose-as-`runner`, and `docker_rootful` gates
across four roles buy nothing on a single-purpose host); jobs straight on the host via `host` labels
(Unix-user isolation only, no Docker builds, breaks workflows that expect a container image).
Kaniko/Buildah are the fallback only if Task 6's docker gate fails.

**What this bounds.** A job can do what `runner` can: read `runner`'s files (including `.runner`,
which the runner must read), read world-readable host files, use disk and CPU. It can't read block
devices, write outside `runner`'s files, read `/home/cda`, or exceed `--memory`. Getting further
takes a kernel or rootlesskit bug.

---

## 5. Tasks

Branch: `git checkout -b claude/runner-rootless origin/master`. Production steps (Task 0 step 6,
Task 1 step 4, Task 5) need **explicit approval at that step**.

### Task 0 — Revoke the job socket on runny, fix the red molecule test

**Files**
- `ansible/plays/roles/forgejo_runner/defaults/main.yml`, below `forgejo_runner_docker_host`:
  ```yaml
  # What JOB containers get as /var/run/docker.sock (config.yml container.docker_host).
  # Separate from forgejo_runner_docker_host, which the RUNNER itself needs.
  # "-" = never mount. Empty is NOT auto-detect on runner 13.2.1: it also mounts nothing.
  # host: "-" because the host socket is root on the host (history/2026-11-22_runny-docker-socket-fix.md).
  forgejo_runner_job_docker_host: >-
    {{ forgejo_runner_docker_host if forgejo_runner_docker == 'dind' else '-' }}
  ```
- `templates/config.yml.j2:48`: render `forgejo_runner_job_docker_host`; rewrite the comment at 40–47.
- `molecule/default/verify.yml:57-65`: fixed-string greps matching the quoted render:
  ```yaml
  cmd: "grep -qF 'docker_host: \"unix:///var/run/dind/docker.sock\"' /home/testuser/runny-dind/data/config.yml"
  ...
  - name: Verify the host config gives job containers NO daemon socket
    ansible.builtin.command:
      cmd: "grep -qF 'docker_host: \"-\"' /home/testuser/runny-host/data/config.yml"
  ```
- `history/2026-11-22_runny-docker-socket-fix.md`: "Superseded 2026-11-23" section (F5 evidence, the
  revoke, pointer to this plan).

**Steps**
1. Edit.
2. Render check. Pass the backend as an extra var (`-e`): `include_vars` outranks play and task vars, so
   setting it in the play renders `"-"` for both backends. Done in Task 0, where the worker hit this.
   ```bash
   mkdir -p /tmp/render && cat >| /tmp/render/play.yml <<'EOF2'
   - hosts: localhost
     connection: local
     gather_facts: false
     vars: {forgejo_runner_capacity: 1, forgejo_runner_labels: [x], forgejo_runner_container_options: "", forgejo_runner_extra_hosts: []}
     tasks:
       - include_vars: {file: /home/cda/dev/infrastructure/container/ansible/plays/roles/forgejo_runner/defaults/main.yml}
       - template: {src: /home/cda/dev/infrastructure/container/ansible/plays/roles/forgejo_runner/templates/config.yml.j2, dest: "/tmp/render/config-{{ forgejo_runner_docker }}.yml"}
   EOF2
   for b in host dind; do ansible-playbook /tmp/render/play.yml -e forgejo_runner_docker=$b; done
   grep -H docker_host /tmp/render/config-*.yml
   ```
   Expected: host → `docker_host: "-"`, dind → `docker_host: "unix:///var/run/dind/docker.sock"`.
3. `cd ansible && ansible-playbook plays/user.yml --syntax-check -i production`.
4. Commit `fix(forgejo_runner): give host-backend jobs no daemon socket; fix quoted docker_host asserts`,
   push, open PR; wait for `Molecule Test (forgejo_runner/default)` = success.
5. servyy-test: `./servyy-test.sh --tags user.docker.runny`; its rendered `config.yml` (path from
   `forgejo_runner_service_dir` in `ansible/testing`) shows `docker_host: "-"`.
6. **Approval**, then `./servyy.sh --tags user.docker.runny --limit runny.lehel.xyz`.
   `ssh runny.lehel.xyz 'grep -n docker_host /home/cda/runny/data/config.yml'` → `"-"`; `runny.runner` restarted.
7. Diag job: `test ! -e /var/run/docker.sock && echo "no socket, as designed"` passes.
8. Merge (fast-forward; `--no-ff` fails on this workstation).

Docker jobs on runny fail until Task 5. The only consumer today is the probe repo.

### Task 1 — Stop the false-positive fail2ban bans (independent)

**File:** `roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2`. In
`get_traefik_crawler_ips` **and** `get_traefik_rate_limit_ips`, add the label-filter stage
`| RequestPath !~ "/api/actions/runner.v1.*"` after `| json` (the gRPC paths are `/api/actions/runner.v1.RunnerService/FetchTask` etc. There is **no** slash after `v1`; a `runner.v1/` pattern matches nothing, as the worker found in Task 1) (see memory `loki_logql_query_quirks`).

**Steps**
1. Run old vs new query against Loki for the last hour (CLAUDE.md "Testing Loki Queries"):
   `92.5.160.254` drops out, other IPs unchanged.
2. Commit `fix(fail2ban): don't count Forgejo runner polling as crawling`.
3. `./servyy-test.sh --tags system.fail2ban`; `ssh servyy-test.lxd 'sudo bash /usr/local/bin/blocklist/update-from-loki.sh'` exits 0.
4. **Approval**, then `./servyy.sh --tags system.fail2ban --limit servy.lehel.xyz`.
5. After a ≥ 10 min runner job: `ssh servy.lehel.xyz 'sudo -n grep -c 92.5.160.254 /var/log/fail2ban-loki.log'` unchanged.

### Task 2 — Rehearsal VM `runny-test`

servyy-test is a privileged LXD container with a dozen root-run services. It can't prove AppArmor or
run without the root-run daemon. Rehearse on a VM shaped like runny.

**Files**
- `scripts/setup_test_runner_vm.sh` (new, idempotent, style of `scripts/setup_test_container.sh`):
  `lxc launch ubuntu:26.04 runny-test --vm -c limits.cpu=2 -c limits.memory=1GiB`, wait for the
  agent, add `~/.ssh/id_rsa.pub` for `ubuntu`, print the IP.
- `ansible/testing`: host `runny-test.lxd` copying runny's host vars from `ansible/production`
  (`root_user: ubuntu`, `create_swap`, `swap_space_override: 4G`, `skip_storagebox`, `restic_skip`,
  `repo_checkout: false`, `loki_blocklist_enabled: false`, `services_enabled: {runny: true}`,
  `forgejo_runner_*` like runny, but `forgejo_runner_instance: http://ci.servyy-test.lxd`,
  `forgejo_runner_name: runny-test`, `forgejo_runner_extra_hosts: ["ci.servyy-test.lxd:<servyy-test IP>"]`).
  Start with `forgejo_runner_docker: host` and `with_docker/with_containers: true`, the same as runny today.
- servyy-test vars: `forgejo_runners: [test, runny-test]`; `ansible/plays/vars/secrets.yml`:
  `forgejo_runner_secrets.runny-test` (same format as existing entries, 40 hex).

**Steps**
1. Script, then `./servyy-test.sh --limit runny-test.lxd` (full).
2. Register the runner on servyy-test's Forgejo (the bootstrap tag; check `plays/user.yml` for it),
   `--limit servyy-test.lxd`.
3. `ssh runny-test.lxd 'docker ps --format {{.Names}}'` → `runny.runner`, `runny.node-exporter`;
   runner `runny-test` online at `ci.servyy-test.lxd`.
4. Push the probe repo (`forgejo-probe`, `forgejo-diag`) to servyy-test's Forgejo.
5. Commit `test: add runny-test VM as the rootless-runner rehearsal host`.

**Stop if** the VM can't reach `ci.servyy-test.lxd`. Fix networking first.

### Task 3 — `rootless` backend in the `forgejo_runner` role (tests first)

Same role, so `config.yml.j2` and the registration secret stay in one place. The container path
(`host`/`dind`) is untouched and moves into a block. `rootless` installs everything on the host
and uses no compose file.

**Files**
- `defaults/main.yml`
  ```yaml
  # rootless: runner-only hosts (runny). forgejo-runner binary + rootless dockerd as
  # systemd --user services of an unprivileged user; root-run Docker is masked.
  forgejo_runner_rootless_user: runner
  forgejo_runner_rootless_subid: "296608:65536"   # next free range on runny
  forgejo_runner_binary_arch: "{{ 'arm64' if ansible_facts.architecture == 'aarch64' else 'amd64' }}"
  forgejo_runner_binary_url: >-
    https://code.forgejo.org/forgejo/runner/releases/download/v{{ forgejo_runner_version }}/forgejo-runner-{{ forgejo_runner_version }}-linux-{{ forgejo_runner_binary_arch }}
  forgejo_runner_binary_path: /usr/local/bin/forgejo-runner
  # Fixed so it can be firewalled and checked (acceptance #12/#13). 0 = runner picks.
  forgejo_runner_cache_port: 0
  forgejo_runner_prune_schedule: "*-*-* 02:00"
  forgejo_runner_prune_flags: "-a -f --volumes"
  ```
  - `forgejo_runner_service_dir`: for `rootless` default `/home/{{ forgejo_runner_rootless_user }}/runny`.
  - `forgejo_runner_docker_host` and `forgejo_runner_job_docker_host`: for `rootless` both
    `unix:///run/user/{{ uid }}/docker.sock`. Jobs get the rootless socket on purpose. The uid comes
    from a `getent` fact registered in `rootless.yml`; define it as
    `forgejo_runner_rootless_uid` there and reference that.
- `templates/config.yml.j2`: add under `cache:` `port: {{ forgejo_runner_cache_port }}` when non-zero
  (leave `host` unset; the runner picks its outbound address).
- `tasks/main.yml`: wrap every existing task from *Look up the deploy user's uid/gid* to *Restart the
  runner* in `block:` with `when: forgejo_runner_docker != 'rootless'`. Add
  `- include_tasks: rootless.yml` with `when: forgejo_runner_docker == 'rootless'`, tagged
  `user.docker.runny`.
- `tasks/rootless.yml` (new). Tag every task `user.docker.runny`; tag `molecule-notest` where marked (†).
  1. † **Mask root-run Docker first**, before anything binds `:9100` or registers. Run
     `systemd: name={{ item }} state=stopped masked=true` for `docker.socket`, `docker.service`, `containerd.service`.
     Mask the socket too, or any `docker` call starts the daemon again. Stopping the daemon also stops the old
     `runny.runner` / `runny.node-exporter` containers, so **no manual `compose down`** is needed. On
     rollback, unmasking brings them back (`restart: unless-stopped`). Stop and disable
     `docker-user-firewall.service` if present. It only installs the `DOCKER-USER` edge rules, while
     runny's `:9100` filter is the separate `node-exporter-firewall` (`INPUT`), so it is unaffected. **Then**
     (after the mask, so `cda` never holds a live daemon mid-play) remove `{{ create_user }}` from
     `docker`. This step needs its own `getent: {database: group, key: docker}`, because the existing
     *Look up the docker group id* task sits in the non-rootless block and is skipped here. Then
     `command: gpasswd -d {{ create_user }} docker` with
     `when: create_user in (ansible_facts.getent_group.docker[2] | default('')).split(',')`. `with_docker: false` only skips `docker_setup.yml` and does not revoke an existing
     membership.
  2. user `runner`: `shell: /usr/sbin/nologin`, `create_home: true`, `groups: ""`, `append: false`.
     Then `getent passwd runner` → set `forgejo_runner_rootless_uid`.
  3. `lineinfile` `/etc/subuid` and `/etc/subgid`: `regexp: '^runner:'`, `line: "runner:{{ forgejo_runner_rootless_subid }}"`.
  4. † Assert the profile is **loaded**, not merely present:
     `grep -qx 'rootlesskit (unconfined)' /sys/kernel/security/apparmor/profiles`.
     (`aa-status --profiled` prints a **count** — `195` on runny — not names, and `aa-status` lists
     only enforce/complain profiles, where this one never appears. Both are traps that would fail a
     good host.) On failure, print §1's AppArmor fact and stop. **Never** write a profile or touch
     the sysctl.
  5. apt: `rootlesskit`, `slirp4netns`, `uidmap`, `dbus-user-session`; plus `prometheus-node-exporter`
     when `forgejo_runner_node_exporter`, then `systemd: name=prometheus-node-exporter enabled=yes
     state=started`. `:9100` is free by now because step 1 stopped the container. Two differences from the
     container it replaces, both harmless but worth recording: the package runs with **native** `/proc`,
     `/sys` and `/` (the container passed `--path.procfs=/host/proc` etc.), and its version here is **1.10.2**
     instead of the container's **1.9.1**, so it exposes a few extra metrics. If dashboards must keep the
     container's mount-point exclusion, set it in `/etc/default/prometheus-node-exporter`. Otherwise
     leave the package default and note the change.
  6. † `loginctl enable-linger runner` (`creates: /var/lib/systemd/linger/runner`).
  7. † `get_url` the binary to `forgejo_runner_binary_path`, mode `0755`, owner root,
     `checksum: "sha256:{{ forgejo_runner_binary_url }}.sha256"`.
  8. Directories (owner `runner`): `~/runny/data` `0750`, `~/.config/systemd/user`, `~/.config/docker`.
  9. Templates (owner `runner`; `notify: restart rootless runner` where noted):
     - `config.yml.j2` → `~/runny/data/config.yml` (shared template, notify)
     - `rootless/docker.service.j2` → `~/.config/systemd/user/docker.service`:
       ```ini
       [Unit]
       Description=Docker Application Container Engine (Rootless)
       [Service]
       Environment=PATH=/usr/share/docker.io/contrib:/usr/sbin:/usr/bin:/sbin:/bin
       ExecStart=/usr/share/docker.io/contrib/dockerd-rootless.sh
       ExecReload=/bin/kill -s HUP $MAINPID
       TimeoutSec=0
       RestartSec=2
       Restart=always
       StartLimitBurst=3
       StartLimitInterval=60s
       LimitNOFILE=infinity
       LimitNPROC=infinity
       LimitCORE=infinity
       TasksMax=infinity
       Delegate=yes
       Type=notify
       NotifyAccess=all
       KillMode=mixed
       [Install]
       WantedBy=default.target
       ```
       (The unit `dockerd-rootless-setuptool.sh` would write. The tool itself isn't used because it
       looks for `dockerd-rootless.sh` next to `/usr/bin/dockerd`, and Ubuntu ships it in contrib.)
     - `rootless/forgejo-runner.service.j2` → `~/.config/systemd/user/forgejo-runner.service` (notify):
       ```ini
       [Unit]
       Description=Forgejo Actions runner ({{ forgejo_runner_name }})
       Requires=docker.service
       After=docker.service
       [Service]
       WorkingDirectory=%h/runny/data
       Environment=DOCKER_HOST=unix://%t/docker.sock
       ExecStart={{ forgejo_runner_binary_path }} daemon --config config.yml
       Restart=on-failure
       RestartSec=5
       [Install]
       WantedBy=default.target
       ```
     - `rootless/daemon.json.j2` → `~/.config/docker/daemon.json`: the same `log-driver`/`log-opts`
       as the root-run daemon (take them from the vars `roles/user/tasks/docker_setup.yml` uses; don't copy values).
     - `rootless/docker-prune.service.j2` + `.timer.j2` → user units: `Environment=DOCKER_HOST=unix://%t/docker.sock`,
       `ExecStart=/usr/bin/docker system prune {{ forgejo_runner_prune_flags }}`,
       `OnCalendar={{ forgejo_runner_prune_schedule }}`, `Persistent=true`.
  10. † `systemd: scope=user name=docker enabled=yes state=started daemon_reload=yes`,
      `become_user: runner`, `environment: XDG_RUNTIME_DIR=/run/user/{{ uid }}`; then `wait_for path=/run/user/{{ uid }}/docker.sock`.
  11. † Register: `command: "{{ forgejo_runner_binary_path }} create-runner-file --instance … --name … --secret …"`,
      `chdir: ~/runny/data`, `creates: ~/runny/data/.runner`, `become_user: runner`, `no_log: true`.
      Then `file: .runner mode=0600 owner=runner`.
  12. † Enable/start `forgejo-runner` and `docker-prune.timer` (user scope, as 10).
  13. † Remove the old container-backend dir. New default:
      `forgejo_runner_legacy_service_dir: "/home/{{ create_user }}/runny"`. First `command: systemctl --user
      is-active forgejo-runner` with `become_user: runner` and `environment: XDG_RUNTIME_DIR=/run/user/{{ uid }}`
      (as in steps 10/12) must return `active` (fail otherwise). Then
      `file: path={{ forgejo_runner_legacy_service_dir }} state=absent`. That directory holds a second
      `.runner` owned by `cda`. Rollback doesn't need it: the `host` backend re-renders the dir and
      re-registers.
  - `handlers/main.yml` (new): `restart rootless runner` → user-scope restart of `forgejo-runner`.
- `molecule/default/converge.yml`: third include with `forgejo_runner_docker: rootless`,
  `forgejo_runner_node_exporter: true`, `forgejo_runner_cache_port: 41500`.
- `molecule/default/verify.yml` (**write first**), on the rootless render:
  user `runner` exists and is in no supplementary group; `/etc/subuid` has exactly one `runner:` line;
  `docker.service` user unit contains `ExecStart=/usr/share/docker.io/contrib/dockerd-rootless.sh`
  and `Delegate=yes`; `forgejo-runner.service` contains `DOCKER_HOST=unix://%t/docker.sock`;
  `~runner/runny/data/config.yml` has `docker_host: "unix:///run/user/<uid>/docker.sock"` and
  `port: 41500`; **no** `docker-compose.yml` in `~runner/runny`; data dir owned by `runner`;
  `prometheus-node-exporter` installed.

**Steps**
1. verify.yml first. Push, and CI fails on the new asserts.
2. Implement. CI green. Commit `feat(forgejo_runner): rootless backend (binary runner + rootless dockerd as user services)`.
3. runny-test: set `forgejo_runner_docker: rootless` and `forgejo_runner_cache_port: 41500`, then
   `./servyy-test.sh --limit runny-test.lxd --tags user.docker.runny`. rootless.yml step 1 stops the old
   containers; there is no manual teardown.
4. Verify:
   ```bash
   ssh runny-test.lxd 'U=$(id -u runner); R="sudo -u runner XDG_RUNTIME_DIR=/run/user/$U";
     $R systemctl --user is-active docker forgejo-runner docker-prune.timer;
     $R DOCKER_HOST=unix:///run/user/$U/docker.sock docker info --format "{{.SecurityOptions}} {{.Driver}} {{.CgroupDriver}}";
     sysctl kernel.apparmor_restrict_unprivileged_userns;
     grep -x "rootlesskit (unconfined)" /sys/kernel/security/apparmor/profiles;
     cat /sys/fs/cgroup/user.slice/user-$U.slice/cgroup.controllers;
     systemctl is-enabled docker.service docker.socket containerd.service'
   # "cpu memory pids": delegation is what makes
   # --memory real. Do NOT grep `aa-status --profiled`: it prints a count (195 here), not names,
   # and `aa-status` lists only enforce/complain profiles, where this one never appears.
   # `systemctl show user@.service -p Delegate` prints nothing on 26.04 (it comes from a
   # /usr/lib drop-in); the live cgroup.controllers line above is the real proof.
   # expect, in order: active ×3 · name=rootless … overlay2|overlayfs systemd · = 1 · rootlesskit (unconfined) · cpu memory pids · masked ×3
   ```
   Runner `runny-test` online at `ci.servyy-test.lxd`.
5. **Record `Driver`.** If it's `fuse-overlayfs` or `vfs`, **stop**: builds will be much slower; report first.

**Stop if:**
- `dockerd-rootless.sh` fails with a userns/AppArmor error. Read it with
  `sudo -u runner XDG_RUNTIME_DIR=/run/user/$U journalctl --user -u docker`. That would falsify §1;
  report and don't flip the sysctl.
- The binary URL or its `.sha256` returns 404. Check the release page for the asset name; don't
  drop the checksum.

### Task 4 — Take runny-test out of the shared Docker plays

**Files**
- `ansible/plays/roles/system/tasks/main.yml:54-57`: import `firewall.yml` when
  `(with_docker | default(false)) or (forgejo_runner_node_exporter | default(false))`, so the
  node-exporter `:9100` filter survives `with_docker: false`.
- `ansible/plays/roles/system/tasks/firewall.yml`: add `with_docker | default(false)` to the
  `when` of the three Docker edge-filter tasks (they assume `DOCKER-USER`).
- `ansible/testing` (runny-test): `with_docker: false`, `with_containers: false`,
  `docker_cleanup: {enabled: false}` (the role's user-level prune replaces it).

**Steps**
1. Commit `feat(system): keep the node-exporter filter on hosts without root-run Docker`.
2. `./servyy-test.sh --limit runny-test.lxd` (**full run**, untagged, `failed=0`). This proves no
   play still needs the root-run daemon.
3. Run it again: no unexpected `changed` (idempotence).
4. Check servyy-test itself still renders the same firewall (it's `with_docker: false` and has no
   node-exporter, so `firewall.yml` stays skipped): `./servyy-test.sh --limit servyy-test.lxd --tags system.firewall --check --diff` → no changes.
5. Run **all 14 §0 checks** against runny-test (jobs from servyy-test's Forgejo; #13 from the
   workstation to the VM IP; #14 against a `curl :9100/metrics` from servyy-test instead of servy).
   During #9 watch `ssh runny-test.lxd 'sudo dmesg -w | grep -i oom'`.
6. Verify rootless.yml step 13 removed `/home/cda/runny` on runny-test (`ssh runny-test.lxd test ! -e /home/cda/runny`).

**Stop if:**
- Step 2 fails in a task that still needs root-run Docker. Gate it on `with_docker` like the edge
  filter, note it in §1, and re-run. Never `--skip-tags` past it.
- #12 fails (cache unreachable). Set `cache.host` explicitly to runny's primary address, then re-test.
- #13 succeeds (cache reachable from outside). Add an INPUT drop for the port in the role before going on.

### Task 5 — Migrate runny · **approval required**

**Files**
- `ansible/production`, `runny.lehel.xyz`: `with_docker: false`, `with_containers: false`,
  `docker_cleanup: {enabled: false}`, `forgejo_runner_docker: rootless`,
  `forgejo_runner_cache_port: 41500`; drop `forgejo_runner_service_dir: /home/cda/runny` (the role
  default applies). Rewrite the comment block above the host (rootless, why, history link).
- `monitor/provisioning/alerting/alert-rules.yml:2958`: the runner-offline description becomes
  `sudo -u runner XDG_RUNTIME_DIR=/run/user/$(id -u runner) systemctl --user status forgejo-runner`
  and `journalctl --user -u forgejo-runner` on runny.
- `.claude/skills/check-server-status/SKILL.md`: runny has no root-run containers; health is the two
  user units + `:9100`.

**Steps** (show the diff and commands, ask before step 3)
1. Merge to master after CI is green; push.
2. No manual steps on runny. rootless.yml step 1 stops the old containers and removes `cda` from `docker`.
3. `cd ansible && ./servyy.sh --limit runny.lehel.xyz` (full run). Verify
   `ssh runny.lehel.xyz 'getent group docker'` lists no `cda`. Without that, acceptance #1 would pass
   only because the daemon is masked.
4. All 14 §0 checks from jobs on `ci.lehel.xyz`.
5. Monitor changes on codey/servy: `./servyy.sh --limit codey.lehel.xyz --tags user.docker.monitor`
   (Grafana alert description); confirm no stale `container_not_running` for `runny.*` in Grafana.
6. Verify rootless.yml step 13 removed `/home/cda/runny` (`ssh runny.lehel.xyz test ! -e /home/cda/runny`).

**Rollback:** restore the host vars (`with_docker/with_containers: true`, `forgejo_runner_docker: host`,
`forgejo_runner_service_dir: /home/cda/runny`), unmask the three units, full deploy `--limit runny.lehel.xyz`.
`docker_setup.yml` re-adds `cda` to `docker`; the runner re-registers. Stop the user units by hand
(`$RUN systemctl --user disable --now forgejo-runner docker`). Remove the `runner` user in a follow-up, not during rollback.

### Task 6 — Benchmark, decide, scope, record

1. Re-run `bench.yml` + `bench-docker.yml` on runny; add a column to §2. Note `available` memory at
   idle vs the 495 MB baseline.
2. **Docker gate:** cold build ≤ ~750 s (2× 374 s) → runny keeps amd64 docker jobs; otherwise
   runny takes no docker jobs, and amd64 images build on GitHub (or codey + QEMU after §9).
   If slirp4netns is the bottleneck, try `DOCKERD_ROOTLESS_ROOTLESSKIT_NET=pasta` in the unit first.
3. **Node gate (separate):** if vitest still times out, decide on capacity (bigger shape, the project's
   hook timeout, or exclude the suite on runny) and record why.
4. **Scope:** re-register runny with `--scope cda` via `roles/forgejo_bootstrap/tasks/main.yml:58`
   (no scope today). Prove a repo outside the scope isn't picked up. Re-test after the v17 deploy.
5. `history/2026-11-23_runner-rootless.md`: problem (F5), decision (§4), files, deploy output, §0
   table with real outputs, benchmark column, rollback. Update `runny/AGENTS.md` (backends: `dind`
   for codey, `host` legacy, `rootless` for runny; how to operate the user units), the CLAUDE.md
   per-server table (runny: rootless, no containers) and its cleanup section (daily, not weekly).
6. `architecture/landscape.yaml`: runny vCPU 1 → 2; `architecture/render.py --verify`.
7. Delete the probe repo once numbers are recorded (`DELETE /api/v1/repos/cda/energy.consumption`,
   basic auth `cda`) and its servyy-test copy.

---

## 6. Risks with a defined response

| Risk | Detected by | Response |
|---|---|---|
| rootless dockerd won't start under AppArmor | Task 3 step 4 | report; don't flip the sysctl |
| storage driver falls back to fuse-overlayfs/vfs | Task 3 step 5 | stop and measure |
| a shared play still needs root-run Docker | Task 4 step 2 | gate on `with_docker` |
| cache unreachable / internet-facing | §0 #12/#13 | set `cache.host` / add INPUT drop |
| memory tight | §0 #9, Task 6 | lower job cap to 700m; else docker gate fails → Task 0 state stays |
| build slow under slirp4netns | Task 6 | try pasta; else Kaniko/Buildah |
| v17 changes F4 / scoping | Task 6 step 4 | re-run after the v17 deploy |

## 7. Not verified yet (and where it gets verified)

| Claim | Verified in |
|---|---|
| Ubuntu's rootlesskit profile is enough with sysctl `1` | Task 3 step 4 |
| contrib `dockerd-rootless.sh` runs under the Task 3 unit | Task 3 step 4 |
| `--memory` enforced under rootless | §0 #9 (Task 4) |
| host-mode runner cache reachable from rootless jobs | §0 #12 (Task 4) |
| binary URL + `.sha256` asset naming for 13.2.1 | Task 3 step 3 |
| `--scope` refuses out-of-scope jobs | Task 6 step 4 |
| `forgejo/upload-artifact` v4/v5 works on 15.0.12 / v17 | Task 6 (add to `bench-docker.yml`) |

## 8. Rollback summary

| Task | Rollback |
|---|---|
| 0 | revert, `--tags user.docker.runny --limit runny.lehel.xyz` |
| 1 | revert, `--tags system.fail2ban --limit servy.lehel.xyz` |
| 2 | `lxc delete -f runny-test`; drop inventory + `forgejo_runners` entry |
| 3–4 | runny-test only; restore its vars |
| 5 | see Task 5 *Rollback* |

## 9. Follow-up: codey (separate plan)

codey keeps privileged dind until runny passes §0. Because codey also runs root-run services
(claude-hub, opencode), it can't drop `with_docker`. It would run the `rootless` backend
**next to** the root-run daemon, so rootless.yml step 1 (masking + group removal) must become conditional. Its amd64 builds need
QEMU binfmt installed on the host (`qemu-user-static` / `binfmt-support`) instead of
`docker run --privileged tonistiigi/binfmt` (`tasks/main.yml:56`). It also needs a check that nothing
sensitive on codey is world-readable (F7). Until then, scope codey's runner (Task 6 step 4).
