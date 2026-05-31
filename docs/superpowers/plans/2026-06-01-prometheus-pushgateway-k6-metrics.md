# K6 Metrics via Pushgateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable k6 to push metrics to Prometheus through SSH tunnel with Prometheus locked to internal network and Pushgateway accepting remote writes.

**Architecture:** 
Remove Prometheus from public proxy network (internal-only via backend network). Add Pushgateway service on internal network to accept k6 metrics pushes. Configure Prometheus to scrape Pushgateway. Deploy via git workflow: branch → test on servyy-test.lxd → user approval → production deployment via ./servyy.sh.

**Tech Stack:** Docker Compose, Prometheus 2.x, Pushgateway 1.x, k6, bash/git

---

## File Structure

```
/home/cda/dev/infrastructure/container/monitor/
├── docker-compose.yml          # Modify: Remove proxy from prometheus, add pushgateway service
├── prometheus.yml              # Modify: Add pushgateway scrape job
├── .git/                        # Git workflow: branch → commit → test → deploy
```

---

## Task 1: Create Feature Branch and Setup

**Files:**
- Modify: `/home/cda/dev/infrastructure/container/monitor/docker-compose.yml`
- Modify: `/home/cda/dev/infrastructure/container/monitor/prometheus.yml`

- [ ] **Step 1: Navigate to container repo and check git status**

```bash
cd /home/cda/dev/infrastructure/container
git status
```

Expected: Clean working tree or shows current branch.

- [ ] **Step 2: Create feature branch**

```bash
git checkout -b feat/prometheus-pushgateway-k6-metrics
```

Expected: Switched to new branch `feat/prometheus-pushgateway-k6-metrics`

---

## Task 2: Remove Prometheus from Proxy Network

**Files:**
- Modify: `/home/cda/dev/infrastructure/container/monitor/docker-compose.yml` (lines 94-96)

- [ ] **Step 1: Edit docker-compose.yml - remove proxy network from prometheus**

Read current prometheus service networks section (lines 94-96):
```yaml
    networks:
      - backend
      - proxy
```

Replace with:
```yaml
    networks:
      - backend
```

Use Edit tool to remove the `- proxy` line from prometheus service.

- [ ] **Step 2: Verify YAML syntax**

```bash
cd /home/cda/dev/infrastructure/container/monitor
docker-compose config > /dev/null 2>&1 && echo "✓ Valid YAML" || echo "✗ Invalid YAML"
```

Expected: `✓ Valid YAML`

- [ ] **Step 3: Commit change**

```bash
cd /home/cda/dev/infrastructure/container
git add monitor/docker-compose.yml
git commit -m "feat: remove prometheus from public proxy network"
```

Expected: Commit message shown.

---

## Task 3: Add Pushgateway Service to Docker Compose

**Files:**
- Modify: `/home/cda/dev/infrastructure/container/monitor/docker-compose.yml`

- [ ] **Step 1: Add pushgateway service after prometheus service**

After the prometheus service (after line 98), add new pushgateway service:

```yaml
  pushgateway:
    image: prom/pushgateway:v1.6.2
    container_name: ${COMPOSE_PROJECT_NAME}.pushgateway
    labels:
      - com.centurylinklabs.watchtower.scope=prod
    volumes:
      - pushgateway_data:/pushgateway
    command:
      - "--persistence.file=/pushgateway/metrics"
      - "--persistence.interval=5m"
    networks:
      - backend
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/-/healthy"]
      interval: 10s
      timeout: 5s
      retries: 3
```

- [ ] **Step 2: Add pushgateway_data volume to volumes section**

In the `volumes:` section at bottom of file (after line 140), add:

```yaml
  pushgateway_data: { }
```

- [ ] **Step 3: Verify syntax and grep to confirm changes**

```bash
cd /home/cda/dev/infrastructure/container/monitor
docker-compose config > /dev/null && echo "✓ Valid YAML"
grep -A 15 "pushgateway:" docker-compose.yml | head -5
```

Expected: Shows pushgateway service added with backend network only.

- [ ] **Step 4: Commit change**

```bash
cd /home/cda/dev/infrastructure/container
git add monitor/docker-compose.yml
git commit -m "feat: add pushgateway service for k6 metrics ingestion"
```

---

## Task 4: Configure Prometheus to Scrape Pushgateway

**Files:**
- Modify: `/home/cda/dev/infrastructure/container/monitor/prometheus.yml`

- [ ] **Step 1: Add pushgateway scrape job to prometheus.yml**

After the prometheus job (after line 6), add new scrape config:

```yaml
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway:9091']
    scrape_interval: 5s
```

Final file should have pushgateway job between prometheus and cadvisor jobs.

- [ ] **Step 2: Verify syntax**

```bash
cd /home/cda/dev/infrastructure/container/monitor
# Test if file is valid YAML
python3 -c "import yaml; yaml.safe_load(open('prometheus.yml'))" && echo "✓ Valid YAML" || echo "✗ Invalid YAML"
```

Expected: `✓ Valid YAML`

- [ ] **Step 3: Show the added config**

```bash
grep -A 4 "job_name: 'pushgateway'" /home/cda/dev/infrastructure/container/monitor/prometheus.yml
```

Expected: Shows pushgateway job config with 5s scrape interval.

- [ ] **Step 4: Commit change**

```bash
cd /home/cda/dev/infrastructure/container
git add monitor/prometheus.yml
git commit -m "feat: configure prometheus to scrape pushgateway for k6 metrics"
```

---

## Task 5: Test Deployment on servyy-test.lxd

**Files:**
- No modifications (testing only)

- [ ] **Step 1: Deploy to test environment**

```bash
cd /home/cda/dev/infrastructure/container
# Setup test container
cd scripts && ./setup_test_container.sh

# Deploy to test
cd ../ansible && ./servyy-test.sh
```

Expected: Deployment completes with no errors.

- [ ] **Step 2: Verify Prometheus is NOT on proxy network**

```bash
ssh servyy-test.lxd "docker inspect servyy_test.prometheus --format='{{.NetworkSettings.Networks | json}}' | grep -i proxy" 2>&1 || echo "✓ Prometheus not on proxy network"
```

Expected: `✓ Prometheus not on proxy network` (grep returns no results)

- [ ] **Step 3: Verify Pushgateway is running and healthy**

```bash
ssh servyy-test.lxd "docker ps | grep pushgateway && echo '✓ Pushgateway running'"
ssh servyy-test.lxd "docker exec servyy_test.pushgateway curl -s http://localhost:9091/-/healthy && echo '✓ Healthy'"
```

Expected:
```
✓ Pushgateway running
✓ Healthy
```

- [ ] **Step 4: Verify Prometheus scrapes pushgateway**

```bash
ssh servyy-test.lxd "docker exec servyy_test.prometheus wget -q -O- http://localhost:9090/api/v1/targets 2>/dev/null | grep -o 'pushgateway' && echo '✓ Pushgateway target registered'"
```

Expected: `✓ Pushgateway target registered`

- [ ] **Step 5: Test k6 push through tunnel to pushgateway**

```bash
# Setup tunnel to test pushgateway
TEST_IP=$(lxc info servyy-test.lxd | grep "inet" | head -1 | awk '{print $2}')

ssh -L 9091:$TEST_IP:9091 servyy-test.lxd sleep 120 &
TUNNEL_PID=$!
sleep 2

# Run k6 test
cd /home/cda/.agent-deck/multi-repo-worktrees/feature-ls-prod-26e45be3/leaguesphere
k6 run load-test-prometheus-test.js \
  --out "experimental-prometheus-rw" \
  -e K6_PROMETHEUS_RW_SERVER_URL="http://localhost:9091" \
  --vus 1 \
  --duration 20s 2>&1 | tail -15

# Kill tunnel
kill $TUNNEL_PID 2>/dev/null || true
```

Expected: k6 test completes successfully, iterations shown.

---

## Task 6: Verify Test Results and Ask for Production Approval

**Files:**
- No modifications (verification only)

- [ ] **Step 1: Verify metrics reached pushgateway on test**

```bash
# Get test container IP
TEST_IP=$(lxc info servyy-test.lxd | grep "inet" | head -1 | awk '{print $2}')

# Query pushgateway metrics
ssh -L 9091:$TEST_IP:9091 servyy-test.lxd sleep 30 &
TUNNEL_PID=$!
sleep 2

curl -s 'http://localhost:9091/metrics' | grep -c 'k6_' && echo "✓ K6 metrics in Pushgateway"

kill $TUNNEL_PID 2>/dev/null || true
```

Expected: Shows count > 0 and `✓ K6 metrics in Pushgateway`

- [ ] **Step 2: Review changes before production**

```bash
cd /home/cda/dev/infrastructure/container
git log --oneline -3
git diff main..feat/prometheus-pushgateway-k6-metrics
```

Expected: Shows the two commits:
1. "feat: remove prometheus from public proxy network"
2. "feat: add pushgateway service for k6 metrics ingestion"
3. "feat: configure prometheus to scrape pushgateway for k6 metrics"

- [ ] **Step 3: Ask user for production deployment approval**

**STOP AND ASK USER:**

Show summary:
- Changes: Prometheus removed from proxy (internal-only), Pushgateway added for k6 metrics
- Tested: Passed on servyy-test.lxd, k6 metrics flow verified
- Ready to deploy to production (lehel.xyz)?

**Wait for explicit user approval before proceeding to Task 7.**

---

## Task 7: Deploy to Production (ONLY after user approval)

**Files:**
- No modifications (deployment only)

- [ ] **Step 1: Deploy to production via ansible**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy.sh --limit lehel.xyz
```

Expected: Deployment completes with no errors.

- [ ] **Step 2: Verify prometheus is running and not on proxy**

```bash
ssh lehel.xyz "docker ps | grep prometheus && docker inspect lehel.prometheus --format='{{.NetworkSettings.Networks | json}}' | grep -v proxy && echo '✓ Prometheus deployed, not on proxy'"
```

Expected: `✓ Prometheus deployed, not on proxy`

- [ ] **Step 3: Verify pushgateway is running**

```bash
ssh lehel.xyz "docker ps | grep pushgateway && echo '✓ Pushgateway running'"
ssh lehel.xyz "docker exec lehel.pushgateway curl -s http://localhost:9091/-/healthy && echo '✓ Healthy'"
```

Expected:
```
✓ Pushgateway running
✓ Healthy
```

- [ ] **Step 4: Test k6 push to production through tunnel**

```bash
# Setup tunnel
ssh -L 9091:pushgateway:9091 lehel.xyz sleep 120 &
TUNNEL_PID=$!
sleep 2

# Run k6 test
cd /home/cda/.agent-deck/multi-repo-worktrees/feature-ls-prod-26e45be3/leaguesphere
k6 run load-test-prometheus-test.js \
  --out "experimental-prometheus-rw" \
  -e K6_PROMETHEUS_RW_SERVER_URL="http://localhost:9091" \
  --vus 1 \
  --duration 20s 2>&1 | tail -15

# Kill tunnel
kill $TUNNEL_PID 2>/dev/null || true
```

Expected: k6 test succeeds with metrics pushed to production Pushgateway.

- [ ] **Step 5: Merge feature branch to main**

```bash
cd /home/cda/dev/infrastructure/container
git checkout main
git merge feat/prometheus-pushgateway-k6-metrics
```

Expected: Fast-forward or merge commit shown.

---

## Self-Review Checklist

✅ **Spec Coverage:**
- [x] Create git branch → Task 1 (git checkout -b)
- [x] Remove Prometheus from proxy network → Task 2 (docker-compose.yml edit)
- [x] Add Pushgateway service → Task 3 (docker-compose.yml append)
- [x] Add Pushgateway scrape job → Task 4 (prometheus.yml edit)
- [x] Test on servyy-test.lxd → Task 5 (./servyy-test.sh)
- [x] Ask user approval → Task 6 (explicit approval checkpoint)
- [x] Deploy to production → Task 7 (./servyy.sh)

✅ **Placeholder Scan:**
- No "TBD", "TODO", "implement later" patterns
- All commands include exact expected output
- All config blocks are complete and production-ready
- Approval checkpoint explicitly documented in Task 6

✅ **Type Consistency:**
- Container names: `${COMPOSE_PROJECT_NAME}.pushgateway` (matches pattern)
- Network: `backend` (internal-only, consistent)
- Job name: `pushgateway` (matches docker service name)
- Port: 9091 (Pushgateway standard)
- SSH tunnel target: `pushgateway:9091` (matches service)
