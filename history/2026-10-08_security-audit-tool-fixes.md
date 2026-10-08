# Security Audit Tool Fixes (2026-10-08)

## Problem

The monthly security audit (`security-audit.timer`) reported that 3 of its 7 tools
were failing or producing no data. Investigation of the `2026-10-04` run found three
distinct root causes.

## Root Causes

### 1. Trivy - results file empty
`run_trivy()` wrote the JSON wrapper (`{"target": ..., "result": ` and `}`) to
`trivy-results.json`, but never redirected `trivy image` stdout into that file. The
scan JSON therefore landed in the tool log (`trivy.log`, 18 MB / 27 `SchemaVersion`
entries) while `trivy-results.json` contained empty `result` values.

### 2. testssl.sh - "cannot exec or find any openssl binary"
testssl.sh was pinned to `v3.0`, which prefers its bundled static
`bin/openssl.Linux.x86_64`. That binary exits non-zero on the current host (OpenSSL
config incompatibility), so `find_openssl_binary()` aborts. Forcing the system
OpenSSL let the version check pass, but v3.0 still hit
"repeated openssl s_client connect problem" under OpenSSL 3.5 (legacy s_client
probing is incompatible). The fix is to use a current testssl.sh release, which
ships a working bundled OpenSSL 1.0.2 and supports OpenSSL 3.x.

### 3. Docker Bench - "Error connecting to docker daemon"
The `docker/docker-bench-security:latest` image ships Docker client v18.06
(API 1.38). The host daemon now enforces a minimum API version of 1.44, so every
`docker` call inside the container fails. The earlier `--privileged` change
addressed a different symptom.

## Fixes

- `ansible/plays/roles/system/templates/security-audit.sh.j2`
  - **Trivy**: redirect each `trivy image` scan into a temp file, validate it as
    JSON, and append it into `trivy-results.json` (fall back to `{}` on failure).
  - **Docker Bench**: derive the daemon's API version via
    `docker version --format '{{.Server.APIVersion}}'` and pass it as
    `DOCKER_API_VERSION` to the container so the bundled client can connect.
  - **testssl.sh**: remove any stale `--jsonfile` before each run (testssl refuses
    to write a non-empty file, which broke same-day re-runs).
- `ansible/plays/roles/system/tasks/security_audit.yml`
  - Bump testssl.sh from `v3.0` to `v3.2.4`.

## Verification (manual, on servy.lehel.xyz)

- testssl.sh v3.2.4 full scan: valid JSON (152 entries), grade **A+**.
- Trivy redirect: `trivy-results.json` parses as valid JSON with populated results.
- Docker Bench with `DOCKER_API_VERSION=<server>`: progresses past section 1 instead
  of aborting with the daemon error.
- Rendered template passes `bash -n`; `ansible-playbook plays/system.yml --syntax-check` passes.

## Deployment

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags system.security_audit
ssh servy.lehel.xyz 'sudo systemctl start security-audit.service'
```
