# 2026-11-25 — Restic maintenance health + authenticated logdy → Loki

## Problem

Three separate silent failures were found on `servy.lehel.xyz`:

1. `restic-forget.service` failed every day since 2026-11-19 (and 2026-09-27 →
   10-09); the weekly `restic check` failed on 2026-11-22. Both were blocked by
   stale exclusive locks left behind by dead processes (`restic-home`,
   `restic-ls-db`). Hourly backups kept saving snapshots because their lock is
   non-exclusive, so snapshot-age alerts stayed green while retention/prune did
   not run for weeks. A one-time, user-approved stale-only `restic unlock`
   removed 8 + 1 locks (no `--remove-all`).
2. Nothing alerted. `Stale Maintenance/Backup Log` checks log *freshness* only:
   `forget.log` and `check.log` are written even when restic fails.
3. Every `logdy` call warned `failed to send to Loki (HTTP 302)`. The shell
   function came from the public `dachrisch/my-prezto` repo and sent only
   `X-Scope-OrgID`; since 2026-11-20 Loki lives on codey behind
   `loki.lehel.xyz` (basicAuth + ipAllowList). The stale `LOKI_URL` in
   `~/.zshenv` pointed at the old `monitor.lehel.xyz` route.

## Solution

### Stale-lock self-heal (no `--remove-all`)

`restic_forget.sh.j2` and `restic_check.sh.j2` now run `restic unlock`
(stale-only) per repo immediately before `forget`/`check`. The unlock output is
appended to the maintenance log and sent to logdy (`Stale lock check complete
tag=<repo> op=<op> detail=…`). A failed unlock is non-fatal — an active backup's
valid lock must never be removed — and the operation's own result is recorded.
The hourly backup scripts are untouched.

### Outcome metrics + alerts

Each script pushes one `restic_maintenance_success{op,repo}` gauge (1 = ok,
0 = failed) for every repo to the local Pushgateway, in a single PUT per op
(`restic_maintenance_forget`, `restic_maintenance_check`) so one repo cannot
erase another. Pushgateway adds `push_time_seconds` to each group.

Two new Grafana rules in `restic-maintenance-alerts`:

* `restic_maintenance_failure`: `restic_maintenance_success == bool 0`
  (medium, `noDataState: OK` — absence is the stale rule's job). **`bool` is
  essential**: plain `== 0` returns the left-hand value `0`, which the rule's
  `> 0.5` threshold can never pass. Measured with `POST /api/v1/eval`:
  `vector(0) == 0` → `0`, `vector(0) == bool 0` → `1`.
* `restic_maintenance_stale`: `time() - (push_time_seconds > 0)` with
  thresholds 129600 s (forget, >36 h) and 691200 s (check, >8 d), plus
  `absent()` and a `vector(0) and on()` tail so a healthy push returns data
  instead of firing `noDataState: Alerting` every evaluation. `push_time_seconds
  > 0` filters rejected pushes, which Pushgateway records as 0.

Read-only `POST /api/v1/eval` of the full A → reduce → threshold pipeline
against the live Grafana (2026-11-25):

| case | C (threshold) |
|---|---|
| failure, synthetic success 0 | `1` |
| failure, synthetic success 1 | `0` |
| fresh forget 60 s / check 3600 s | `0` |
| forget 140000 s old | `[0, 1]` → fires |
| check 700000 s old | `[0, 1]` → fires |
| absent (current live state) | `[1, 1]` → fires |

The absent result is why the rules must ship **after** the first real push.

### logdy → authenticated Loki

`roles/user` renders `~/.config/logdy/loki.env` (0600, owner `create_user`)
from `monitor_loki_url`, `monitor_loki_auth_username`,
`monitor_remote_auth.loki_password` and `monitor.loki_tenant`; the template is
`no_log` and the value lives only in the encrypted vault. The public `my-prezto`
function now sources that file (honouring `LOGDY_LOKI_ENV`) before every call,
so the stale `LOKI_URL` exported by `zshenv` is overridden, and adds `-u
user:password` alongside `X-Scope-OrgID`. The old endpoint literal was removed
from the function itself. `zshenv` is git-crypt encrypted in `my-prezto` and the
key is not available in this checkout, so its stale export remains in that
file but is inert: the env file is authoritative and is sourced on every push.

## Tests

* `ansible/tests/restic_maintenance/test_scripts.py` renders both scripts and
  runs them under zsh with stub `restic`/`curl`: unlock once per repo before
  forget/check, never `--remove-all`, unlock output logged, per-repo gauges
  pushed even when one repo fails, hourly backup has no unlock. RED observed
  before the template change (5 failures), GREEN after (6/6).
* `ansible/plays/roles/system/molecule/restic-maintenance/` (registered in
  `.github/molecule-matrix.yml`) converges the real templates and verifies the
  same contract with stub binaries in CI.
* `ansible/tests/monitor_alerts/test_restic_maintenance_rules.py` pins the rule
  UIDs, datasource, thresholds, `bool` comparison and `noDataState` (4/4).
* `ansible/tests/logdy_loki/test_render.py` pins the env-file contract (3/3);
  `my-prezto` `tests/test_logdy_auth.py` runs the real function with a stub
  curl and proves the env file beats a stale zshenv URL (2/2).
* `yamllint` clean on all changed YAML; molecule-matrix consistency 25/25.

## Files changed

`servyy-container` (branch `claude/restic-maintenance-health`):

* `ansible/plays/roles/system/templates/restic_{forget,check}.sh.j2`
* `ansible/plays/roles/system/defaults/main.yml`
* `ansible/plays/roles/system/molecule/restic-maintenance/*`
* `ansible/plays/roles/user/tasks/{main.yml,logdy_loki.yml}`
* `ansible/plays/roles/user/templates/logdy-loki.env.j2`
* `monitor/provisioning/alerting/alert-rules.yml`
* `ansible/tests/{restic_maintenance,logdy_loki}/*`,
  `ansible/tests/monitor_alerts/test_restic_maintenance_rules.py`
* `.github/molecule-matrix.yml`, `.github/workflows/ci.yml`, this note

`dachrisch/my-prezto` (separate PR): `custom/functions/logdy`,
`tests/test_logdy_auth.py`.

## Production deploy (staged, awaiting approval — NOT run here)

```bash
# 1) scripts + private env file on servy, no monitor tag:
cd /tmp/opencode/servyy-container-locks/ansible
./servyy.sh --limit servy.lehel.xyz --tags "user.repo.clone,system.restic.maintenance,user.zprezto"

# 2) wait for the NEXT NATURAL 05:00 restic-forget run (do not trigger it);
#    verify success for every repo and fresh push_time_seconds for both jobs:
ssh servy.lehel.xyz "curl -sf http://127.0.0.1:9091/metrics | grep -E '^(restic_maintenance_success|push_time_seconds\{job=\"restic_maintenance)'"

# 3) only then provision the rules through Grafana on codey:
./servyy.sh --limit codey.lehel.xyz --tags "user.repo.clone,user.docker.monitor"

# 4) logdy end-to-end from servy (credentials never printed):
ssh servy.lehel.xyz 'zsh -c "source ~/.zprezto/custom/functions/logdy; logdy info maintenance-health-test marker=restic-maintenance-health"'
```

Do not merge/ship step 3 before step 2's first push. Verification after step 4:
query the `marker=restic-maintenance-health` line back through Loki
`/loki/api/v1/query_range` with the authenticated route.
