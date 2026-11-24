# Docker CIS hardening triage + servy audit refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the 2026-11-24 Docker Bench warnings into a documented accept-list plus a small, tested hardening pilot, and bring servy's audit tooling/sshd config in line with codey once its in-flight audit finishes.

**Architecture:** Two independent tracks. Track A is a documentation-first triage followed by one narrowly scoped compose pilot (`bumbleflies`, the only statics service enabled on `servyy-test.lxd`), tested before any production rollout. Track B is a narrow-tag deploy of changes already merged to master, gated on servy's audit completing so its running bash script is not overwritten mid-execution.

**Tech Stack:** Ansible `system` role (`system.hardening.ssh`, `system.security_audit`, `user.docker.bumbleflies`), docker-compose, Docker Bench for Security v1.6.1 (source checkout), Molecule `system/core`, `sshd -T` verification.

---

## Track A — Docker CIS warning triage

### Task A1: Write the warning triage register

**Files:**
- Create: `history/2026-11-24_docker-cis-warning-triage.md`

**Step 1: Capture the evidence**

```bash
ssh codey.lehel.xyz 'sed -r "s/\x1B\[[0-9;]*[mK]//g" /var/log/security-audit/2026-11-24/docker-bench.log | grep "^\[WARN\]" | sort | uniq -c | sort -rn > /tmp/codey-warns.txt'
ssh servy.lehel.xyz 'sed -r "s/\x1B\[[0-9;]*[mK]//g" /var/log/security-audit/2026-11-24/docker-bench.log | grep "^\[WARN\]" | sort | uniq -c | sort -rn > /tmp/servy-warns.txt'
```

Codey: 117 checks, 149 WARN, **0 FAIL**. Servy: 105 checks, ~427 WARN, **0 FAIL**.

**Step 2: Write the ADR with one row per cluster**

| Cluster | Decision | Reason |
|---|---|---|
| Running as root (vendor images: mariadb, mongo, redis, grafana, traefik, …) | accepted | image default; changing UID breaks data permissions |
| Docker socket mounted (Portainer, Ofelia, watchtower, runner/dind) | accepted | those tools are the socket clients by design |
| Privileged ports 80/443 + wildcard bind on `traefik.traefik` | accepted | Traefik is the edge; only 80/443 published on the host |
| Root FS mounted R/W, no CPU/memory limits, restart policy | accepted | app needs writable roots; limits were measured to cause OOM; restart `unless-stopped` is deliberate |
| `no-new-privileges` | accepted for now | `bumbleflies` sets `PUID`/`PGID`, so its entrypoint very likely uses `su-exec`/`gosu`; blanket use would break it |
| PIDs limit / init process | **actionable** | low-risk, testable |
| Healthcheck missing on image | accepted | image-level, not a compose defect; several already have compose overrides |

**Step 3: Commit**

```bash
git add history/2026-11-24_docker-cis-warning-triage.md
git commit -m "docs: triage Docker Bench warnings from the 2026-11-24 audits"
```

### Task A2: Add the pilot hardening to `bumbleflies/docker-compose.yml`

**Files:**
- Modify: `bumbleflies/docker-compose.yml` (services `www`, `bnb`, `edu`, `live`)

**Step 1: Add the two keys to each of the four services**, e.g. under `restart: unless-stopped`:

```yaml
    pids_limit: 512
    init: true
```

**Step 2: Validate the compose file**

```bash
cd bumbleflies && docker-compose config --quiet
```
Expected: no output, exit 0. (If Docker is unavailable locally, use `ansible-playbook servyy.yml --syntax-check -i testing` plus a YAML parse; the test-host deploy is the authoritative check.)

**Step 3: Commit**

```bash
git add bumbleflies/docker-compose.yml
git commit -m "fix(bumbleflies): cap PIDs and reap zombies in all four containers"
```

### Task A3: Test on servyy-test.lxd

**Step 1: Deploy only that service**

```bash
cd ansible && ./servyy-test.sh --tags user.docker.bumbleflies
```
Expected: `failed=0`, `unreachable=0`; the four `bumbleflies.*` containers are recreated.

**Step 2: Verify runtime state**

```bash
ssh servyy-test.lxd 'docker ps --format "{{.Names}}\t{{.Status}}" | grep bumbleflies'
ssh servyy-test.lxd 'for c in bumbleflies.www bumbleflies.bnb bumbleflies.edu bumbleflies.live; do docker inspect -f "{{.Name}} Pids={{.HostConfig.PidsLimit}} Init={{.HostConfig.Init}}" $c; done'
```
Expected: all Up (healthy where a healthcheck exists), `Pids=512`, `Init=true`.

**Step 3: If any container fails to start**, revert the commit (`git revert HEAD`), re-deploy to the test host, and stop. Do not continue to production.

### Task A4: Production rollout to servy

**Step 1: Ask for approval** before the production deploy; show that four containers will be recreated.

**Step 2: Deploy**

```bash
cd ansible && ./servyy.sh --tags user.docker.bumbleflies --limit servy.lehel.xyz
```

**Step 3: Verify** the same four checks as A3, plus `curl -I https://bumbleflies.de` → 200/301.

**Step 4: Measure the delta** by running only Docker Bench on servy (`sudo /opt/security-audit/docker-bench-security/docker-bench-security.sh -b -l /tmp/bench-after.log`) and comparing the WARN count to 427. Expect a small drop, not a large one — most WARNs are accepted by design.

### Task A5: Close out Track A

- Update the ADR from Task A1 with the actual before/after WARN counts and the verification result.
- Commit: `docs: record Docker CIS triage and bumbleflies pilot results`.

---

## Track B — servy audit refresh

### Task B1: Gate on the running audit

**Step 1: Wait for the summary**

```bash
ssh servy.lehel.xyz 'cat /var/log/security-audit/2026-11-24/SUMMARY.md'
```
Do not proceed while the file is absent — the audit script is a running bash file and must not be overwritten. A check-back automation is already scheduled for 22:05 local.

**Step 2: Record the completed summary** next to codey's result in the final report to the user.

### Task B2: Deploy the narrow sshd hardening

**Files:** none (deploy only; the change is already on master as `57c57983`).

```bash
cd ansible && ./servyy.sh --tags system.hardening.ssh --limit servy.lehel.xyz
```

Verify:

```bash
ssh servy.lehel.xyz 'sudo /usr/sbin/sshd -T | grep -i x11forwarding; grep -n X11Forwarding /etc/ssh/sshd_config.d/99-hardening.conf'
```
Expected: `x11forwarding no` and the drop-in line present.

### Task B3: Deploy the corrected audit tooling

The fix is already on master as `4d3c717f` (arm64/Windows-label/tool-failure reporting). Deploy the whole audit tag so the Docker Bench source checkout is included:

```bash
cd ansible && ./servyy.sh --tags system.security_audit --limit servy.lehel.xyz
```

Verify:

```bash
ssh servy.lehel.xyz '
grep -n "Host\*\*:" /opt/security-audit/security-audit.sh
grep -n "tool_failed" /opt/security-audit/security-audit.sh
sudo git -C /opt/security-audit/docker-bench-security describe --tags --always
file /usr/local/bin/nuclei | cut -c1-120
'
```
Expected: `- **Host**: {{ inventory_hostname }}` (renders `servy.lehel.xyz`), `tool_failed` present, bench `v1.6.1`, nuclei `x86-64`.

### Task B4: Close out Track B

- Do **not** re-run the full audit — it takes ~2h; the next monthly run (Dec 6) uses the new script.
- Write a short history entry recording both narrow deploys and the verification output.
- Commit and push master if the entry is added.

---

## Risks and explicit non-goals

- Compose changes recreate containers: brief downtime on servy, hence test-host first and explicit approval.
- `no-new-privileges`, memory/CPU limits, read-only root FS, and user-namespace remap are **out of scope** for this plan — they break the PUID/PGID entrypoints or the shared data services.
- Track B is blocked until servy's audit writes `SUMMARY.md`; no deploy touches that host before then.
- No changes to codey in this plan — its hardening and audit setup are already verified clean.
