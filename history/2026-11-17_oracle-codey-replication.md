# ADR: Replicate codey.lehel.xyz onto an Oracle Always Free A1 instance

**Date:** 2026-11-17
**Status:** Proposed — server-level replica verified, data migration and DNS cutover outstanding
**Relates to:** ADR (Oracle free-tier capability survey, 2026-11-17)

## Context

`codey.lehel.xyz` runs the dev gateway (opencode + authgate), devhub and the
Portainer/Ofelia/watchtower sidecars on a 2-core / 1.9 GB VPS whose root
filesystem was at **93 % of 29 GB with 2.1 GB free** — the tightest number in
the estate. servy was simultaneously at load 3.04/4 cores with 3.2 GB of swap
in use, so there was no spare capacity to absorb anything.

An Oracle Cloud Always Free tenancy (`dachrischx`, home region `eu-frankfurt-1`)
was available and entirely empty: no instances, volumes, VCNs, databases or
buckets. Its measured allowances are 200 GB block storage (`total-free-storage-gb`),
2 Autonomous Databases (`adb-free-count`), 2 × 10 Mbps load balancers, and a
4 OCPU / 24 GB A1 ARM allotment. The tenancy's A1 limit reports 41 cores
available per AD, higher than a free-only account would show, which suggests an
upgraded (pay-as-you-go) tenancy that keeps the Always Free allowances — this
run deliberately stays inside 4 OCPU / 24 GB / 200 GB so it costs nothing
either way.

## Decision

Provision a 2 OCPU / 12 GB / 100 GB `VM.Standard.A1.Flex` (half the free
allowance, leaving the other half for a later workload) via a git-tracked,
idempotent OCI CLI script, then configure it with the **existing Ansible
playbooks** rather than any bespoke provisioning, by adding one host block to
`ansible/production`.

Reject: a per-host bespoke playbook (duplicates the fleet's configuration and
drifts), and Terraform (adds a toolchain the repo does not use for anything
else).

## Consequences

### Positive

- ✅ codey's role now has a verified replica on a 4× larger disk and 6× more RAM.
- ✅ Whole-stack replication is one inventory block; no new roles were needed.
- ✅ Certs are issued via DNS-01 while DNS still points at codey, so the replica
  is verifiable (`curl --resolve`) *before* any user-visible change.
- ✅ Four latent fresh-host bugs were found and fixed in shared roles (below),
  which benefits every future host, not just this one.

### Negative / Tradeoffs

- ⚠️ **A1 is aarch64.** `dachrisch/devhub` is published **amd64-only**, so devhub
  is disabled on this host (`devhub: false`) and is the one service not yet
  replicated. Needs either a multi-arch image build or binfmt/QEMU emulation.
- ⚠️ Oracle block storage is network-attached; not local NVMe.
- ⚠️ No Hetzner Storage Box reachable from Oracle, so `skip_storagebox: true`
  and the restic target is not configured on this host.
- ⚠️ `tree-sitter*` wheels fail to build on ARM and `graphify install` fails, so
  the graphify skill is unavailable inside the container on this host.
- ⚠️ First boot is slow: opencode provisions ~16 repo checkouts before it starts
  listening, so the container is `unhealthy` for several minutes by design.

**Parallel access (both stacks live, 2026-11-17):**

Instead of shutting codey down to test, the instance serves under its own names
so both run side by side with zero user impact:

| Name | Resolves to | Serves |
|---|---|---|
| `code.lehel.xyz` | codey (v4 + v6) | codey's opencode (unchanged) |
| `codacle.lehel.xyz` | Oracle (A + AAAA) | the replica |
| `traefik.codacle.lehel.xyz` | CNAME → codacle | replica's dashboard (401) |

Records added to Porkbun (all TTL 600): `codacle` A + AAAA, `traefik.codacle`
CNAME → `codacle.lehel.xyz`, mirroring the existing `code` → `codey` pattern.
Explicit records are required because the `*.lehel.xyz` wildcard points at
servy — an unrecorded name never reaches Oracle at all.

`dns_short_name: "codacle"` and `traefik_service_host:
traefik.codacle.lehel.xyz` in the host block drive the Traefik host labels and
the DNS-01 cert. Verified: **HTTP 200 with a valid LE cert over both IPv4 and
IPv6**, while `curl --resolve code.lehel.xyz:443:138.2.180.191` now returns 404
(catch-all) — proof the replica no longer claims codey's name at all.

Known coupling: `traefik/dynamic.yaml` hardcodes
`Host(\`code.lehel.xyz\`)` on the `opencode-apikey` router, so the API-key path
is still bound to that name. Programmatic clients that call
`OPENCODE_BASE_URL=https://code.lehel.xyz` (devhub, dontforget, groceries, queen)
therefore keep talking to codey during the parallel phase; on the replica they
would hit the UI router instead. At cutover this needs either that router
generalised or the clients repointed.

### Implementation Details
**Files added:**
- `scripts/provision-oracle-codey.sh` (NEW) — idempotent VCN/IGW/route/security-list/
  subnet/instance provisioning, `--status` for inspection.

**Files modified:**
- `ansible/production` (MODIFY) — `oracle-codey.lehel.xyz` host block.
- `ansible/plays/roles/system/tasks/security_audit.yml` (MODIFY) — two fixes.
- `ansible/plays/roles/system/tasks/main.yml` (MODIFY) — import `ipv6.yml`.
- `ansible/plays/roles/system/tasks/ipv6.yml` (NEW) — static IPv6 netplan.
- `ansible/plays/roles/user/tasks/atuin.yml` (MODIFY) — config-path detection.
- `ansible/plays/vars/default.yml` (MODIFY) — `python3-requests` in `sys_packages`.

**Fresh-host bugs found and fixed (all pre-existing, none Oracle-specific):**

1. **Trivy keyring unreadable by apt.** `gpg --dearmor` honours the umask, so the
   keyring landed `0640 root:root`; apt verifies as `_apt` and reported
   `NO_PUBKEY 35B8ACA44FD9CA9F`, failing the play. Now `chmod 0644`'d explicitly.
2. **testssl.sh pin unreachable.** `drwetter/testssl.sh` moved to the `testssl`
   org and the old URL advertises **zero refs**; `v3.2.4` exists in neither. Also
   `depth: 1` only fetches the default branch, so a tag checkout can never
   succeed. Now canonical URL + `v3.2.3` (newest 3.2 tag) and no `depth`.
   *Note: this moves servy from v3.2.4 → v3.2.3 on its next run.*
3. **atuin config path drifted.** atuin 18.24.8 creates `~/.atuin/config.toml`;
   18.24.3 (servy, codey) uses `~/.config/atuin/config.toml`. The role hardcoded
   the XDG path, so a fresh host failed outright. Now detects which file exists.
4. **`python3-requests` missing.** Nothing in the repo installs it; it only ever
   arrived transitively on the old hosts, so `docker_network` failed with
   "Failed to import the required Python library (requests)". Added to
   `sys_packages`.

**Provisioning gotchas (OCI):**
- VCN `dnsLabel` must be ≤ 15 chars *and* letters/digits only.
- A new VCN ships a **default route table with no rules** and a **default
  security list opening only 22**, so "create if absent" silently produced an
  instance with no internet route and no 80/443. The script now *ensures* the
  rules instead of assuming absence means "create".
- The public IP is exposed as `data[0]."public-ip"` from
  `compute instance list-vnics`, not from `network vnic get`.
- The image has no root login, so the system play connects as `ubuntu`
  (`root_user: ubuntu`) and creates `cda` as everywhere else.
- `ansible_ssh_common_args: '-o IdentitiesOnly=yes'` is required: the local
  agent otherwise offers enough keys to trip sshd's `MaxAuthTries`
  ("Too many authentication failures").
- **`oci network vnic assign-ipv6` is broken in oci-cli 3.96.x.** It passes
  `hostname=` to an SDK method with no such parameter — `TypeError: assign_ipv6()
  got an unexpected keyword argument 'hostname'` — and the SDK (2.192.0) exposes
  `create_ipv6`, not `assign_ipv6`, so upgrading the CLI does not help. The REST
  call `POST /20160918/ipv6` works, so the script uses `raw-request` (note it
  returns camelCase keys, unlike the CLI).

**IPv6 (enabled 2026-11-17):**

Enabling IPv6 on an OCI VCN is not a toggle but five coordinated changes:
VCN `/56` (`add-ipv6-vcn-cidr --is-oracle-gua-allocation-enabled`), a subnet
`/64` carved from it (`<h1>:<h2>:<h3>:<h4[0:2]>01::/64`), a `::/0 → igw` route
rule, security-list rules for `::/0` **plus ICMPv6 (protocol 58)**, and an
address on the VNIC. Result: `2603:c020:802e:5f01:0:876f:f045:3504`.

Two things worth remembering:

- **ICMPv6 is not optional.** It carries neighbour and path-MTU discovery;
  omitting it yields connections that hang on larger responses instead of
  failing cleanly.
- **OCI's RA delivery is a trap with Docker.** OCI hands out the address and
  default route by router advertisement, but Docker sets
  `net.ipv6.conf.*.forwarding=1`, which leaves `accept_ra=0`. The RA-derived
  address and route therefore carry expiry timers and are never renewed
  (measured: default route expiring in ~2.5 h), so IPv6 dies silently, and does
  not return after a reboot. Fixed by pinning the address and the VCN router's
  EUI-64 link-local (`fe80::200:17ff:fecf:724`, from
  `virtual-router-mac 00:00:17:cf:07:24`) statically in netplan with
  `accept-ra: false`, deployed by `roles/system/tasks/ipv6.yml` (gated on
  `ipv6_address is defined`).

**Testing & Verification:**
- ✅ `plays/system.yml` → `ok=144, failed=0`.
- ✅ `plays/user.yml` → `ok=150, failed=0`.
- ✅ `plays/opencode_authgate.yml` → `ok=3, failed=0`.
- ✅ Containers all arm64-native and running: traefik, error-pages, opencode,
  authgate, portainer agent, ofelia, watchtower ×2.
- ✅ `curl --resolve code.lehel.xyz:443:138.2.180.191` → **HTTP 200**,
  `ssl_verify_result=0`; cert `CN=code.lehel.xyz`, issuer Let's Encrypt.
- ✅ `traefik.code.lehel.xyz` → 401 (dashboard basic-auth enforced).
- ✅ `h.code.lehel.xyz` → no route (devhub intentionally absent).

### Known Issues & Limitations

- devhub not replicated (amd64-only image).
- opencode state (sessions DB, checkouts) is a **fresh** provision, not a copy of
  codey's — no `opencode_opencode_root` / `codey_dev_checkouts` data migration yet.
- No restic backup target configured on this host.
- DNS still points at codey; cutover not performed.

## Alternatives Considered

**Run on an x86 free shape instead** — the only free x86 shapes are 2 ×
`E2.1.Micro` (⅛ OCPU, 1 GB), which cannot host opencode. Rejected: A1 ARM is the
only shape with real capacity, so the ARM constraint had to be solved anyway.

**QEMU/binfmt emulation for devhub** — deferred, not rejected; it is the
zero-other-repo-change path if a multi-arch build proves slow to land.
