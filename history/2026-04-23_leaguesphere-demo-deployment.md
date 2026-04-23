# LeagueSphere Demo Deployment (2026-04-23)

## Summary
Deployed LeagueSphere demo environment to production with automated nightly reset via Ofelia scheduler.

## What Changed
- **Service:** LeagueSphere demo (frontend, backend API, MariaDB database)
- **Location:** `lehel.xyz` (production infrastructure)
- **URL:** `https://demo.leaguesphere.app`
- **Container Names:** `leaguesphere-demo.{www,demo-app,mysql}`
- **Automation:** Ofelia scheduler configured for daily 00:00 UTC reset

## Deployment Status
✅ **Successfully Deployed** on 2026-04-22 via CircleCI

**Demo Containers Running:**
- `leaguesphere-demo.www` - Frontend (nginx reverse proxy)
- `leaguesphere-demo.demo-app` - Django backend API (gunicorn)
- `leaguesphere-demo.mysql` - MariaDB database

## Reset Procedure
**Automated Nightly Reset:**
- **Schedule:** 0 0 0 * * * (midnight UTC daily)
- **Orchestrator:** Ofelia scheduler (`portainer.ofelia` container)
- **Command:** `/bin/bash -c "rm -f /app/.demo_last_reset && /app/entrypoint.demo.sh"`

**Manual Reset (if needed):**
```bash
ssh lehel.xyz "docker exec leaguesphere-demo.demo-app /bin/bash -c 'rm -f /app/.demo_last_reset && /app/entrypoint.demo.sh'"
```

### Reset Actions
1. **Migrations:** Apply pending Django database migrations
2. **Data Seeding:** Initialize demo data with:
   - 4 associations
   - 4 leagues
   - 3 seasons
   - 12 teams
   - 87 players
   - Demo user accounts
3. **Snapshot:** Create database snapshot at `/app/snapshots/demo_snapshot.json`

### Reset Verification (2026-04-23 00:00 UTC)
✅ Reset executed successfully by Ofelia scheduler:
- **Duration:** 33.25 seconds
- **Status:** Passed (no errors)
- **Output:**
  ```
  [2026-04-23T00:00:00Z] Initializing demo database...
  [2026-04-23T00:00:11Z] Migrations completed
  ✓ Created 4 associations
  ✓ Created 4 leagues
  ✓ Created 3 seasons
  ✓ Created 12 teams
  ✓ Created 87 players
  ✓ Created demo user accounts
  ✓ Demo snapshot created at /app/snapshots/demo_snapshot.json
  [2026-04-23T00:00:33Z] Entrypoint script completed, application ready
  ```

## Documentation Updated
- **CLAUDE.md:** Added LeagueSphere demo to Key Services table and Quick Reference
- **AGENTS.md:** Added demo verification commands to validation section
- **GEMINI.md:** Added comprehensive demo management section with reset procedures

## Monitoring & Health Checks
**Container Health Checks:**
- Frontend (`www`): HTTP healthcheck via nginx
- Backend (`demo-app`): `curl -A healthcheck http://localhost:8000/health/?format=json` (interval: 15s, retries: 10)
- Database (`mysql`): `mariadb -h localhost -u root -e 'SELECT 1'` (interval: 15s, retries: 15)

**Verify Status:**
```bash
ssh lehel.xyz "docker ps | grep leaguesphere-demo"
ssh lehel.xyz "docker logs leaguesphere-demo.demo-app --tail 20"
curl -s https://demo.leaguesphere.app/health/
```

## Service Routing (Traefik)
- **HTTPS (Let's Encrypt DNS):** `demo.leaguesphere.app` (via `letsencrypthttpresolver`)
- **Production DNS:** Maps to `leaguesphere-demo.lehel.xyz` via Hetzner DNS
- **Local:** `leaguesphere-demo.lehel` (local network)

## Files Changed
- **Image Repo:** `leaguesphere/frontend:demo` and `leaguesphere/backend:demo`
- **Config Location:** `/home/cda/dev/leaguesphere/deployed/docker-compose.demo.yaml`
- **Environment:** Managed via Ansible `ls_demo` role

## Known Issues & Limitations
None at this time. Demo runs smoothly with automated resets.

## Future Enhancements
- Monitor demo reset performance (currently 33 seconds)
- Consider backup rotation for snapshots
- Add dashboard for demo uptime/health in Grafana

## Deployment Checklist
- [x] LeagueSphere demo containers running
- [x] Ofelia scheduler executing nightly resets
- [x] Manual reset procedure verified
- [x] All health checks passing
- [x] Documentation updated (CLAUDE.md, AGENTS.md, GEMINI.md)
- [x] Demo accessible at `https://demo.leaguesphere.app`

## Rollback Procedure (if needed)
1. Stop demo containers: `ssh lehel.xyz "docker compose -f /home/cda/dev/leaguesphere/deployed/docker-compose.demo.yaml down"`
2. Remove Ofelia labels from demo-app service
3. Redeploy via Ansible: `cd ansible && ./servyy.sh --tags "ls.demo" --limit lehel.xyz`
