# ADR-004: Service Undeployment via Inventory Control

**Date:** 2026-08-28  
**Status:** Accepted  
**Relates to:** ADR-001 (Infrastructure as Code)

## Context

Previously, no dedicated undeployment workflow existed. Services could only be removed manually via SSH or reactively during troubleshooting, creating:
- Inconsistent state between git and production servers
- No audit trail of service removals
- Risk of accidental re-deployment of removed services
- Violation of infrastructure-as-code principles
- Manual operations on production violate deployment policy

We needed a safe, repeatable, git-tracked way to decommission services while preventing accidental re-deployment.

## Decision

Implement a three-part Ansible-based service removal system:

1. **Interactive Removal Playbook** (`ansible/plays/remove_service.yml`)
   - Prompts for service name and confirmation
   - Removes containers, volumes, and service directories
   - Uses pause task for safe variable handling
   - Provides post-removal instructions

2. **Inventory-Based Service Control** 
   - Restructure `ansible/production` from `services: [list]` to `services_enabled: {dict}`
   - Enable/disable services with true/false flags
   - All services default to true (current behavior)

3. **Automatic Filtering**
   - Add pre_task in `ansible/plays/user.yml` to convert dict → list
   - Maintains 100% backward compatibility with existing when conditions
   - Disabled services automatically skipped during deployment

This approach keeps all changes in version control and prevents services from being re-deployed after removal.

## Consequences

### Positive
- ✅ All service removals tracked in git with full history
- ✅ Prevents accidental re-deployment via inventory flags
- ✅ Interactive confirmation prevents mistakes
- ✅ Backward compatible (all services default to enabled)
- ✅ No manual server operations needed
- ✅ Reversible (re-enable by changing flag to true)
- ✅ Works across all infrastructure environments (lehel.xyz, code.lehel.xyz, test)
- ✅ Follows infrastructure-as-code principles

### Negative / Tradeoffs
- ⚠️ Added complexity to inventory structure (dict vs list)
- ⚠️ Pause task doesn't work in non-interactive CI mode (must use `-e` variables)
- ⚠️ Requires git workflow discipline (can't manually SSH to fix)
- ⚠️ Pre-task adds minimal overhead to every deployment

### Implementation Details

**Files Modified:**
- `ansible/plays/remove_service.yml` (NEW)
- `ansible/production` (services → services_enabled dict)
- `ansible/plays/user.yml` (+pre-task for filtering)
- `CLAUDE.md` (+removal workflow section)
- `opencode/scripts/provision-dev.sh` (unrelated: gh-dash topic change)

**Commits:**
- 9c5edf8 docs: add history entry for service undeployment workflow
- 374a0c5 fix: use pause task instead of vars_prompt for confirmation
- 4e7b6d8 feat: implement service undeployment workflow via Ansible
- d6d865e feat: use gh-dash topic for opencode repo discovery

**Testing & Verification:**

✅ Playbook syntax verified with target_host parameter  
✅ Manual removal tested on servyy-test.lxd (removed platzler-heid)  
✅ Verified service directory cleanup on test  
✅ Inventory control verified: opencode skipped on lehel.xyz (not in its services_enabled)  
✅ Tag-based deployment tested: only opencode tasks ran with `--tags "docker,user.docker.opencode"`  
✅ Production deployment successful on code.lehel.xyz  
✅ Container running and healthy  
✅ gh-dash topic discovery confirmed in logs: `[provision-dev] discovering repos with 'gh-dash' topic...`

**Key Learnings:**

1. **vars_prompt limitation** - Cannot reference undefined variables between prompts; switching to pause task for two-step confirmation avoids this
2. **Permission handling** - Ansible-written files with root ownership need pre-cleanup on subsequent runs; resolved by deleting known_hosts before redeployment
3. **Inventory as control layer** - Dict structure enables powerful conditional logic; dict2items filter with selectattr provides clean conversion to list
4. **Role invocation filtering** - Tag filtering works at role inclusion level (when conditions), not just at task level; allows selective service deployment
5. **Backward compatibility patterns** - Pre-task conversion maintains 100% compatibility with existing conditions without modifying role logic
6. **Inventory clarity** - Services disabled in inventory stay disabled even when tagged; prevents accidental re-deployment to wrong hosts

### Known Issues & Limitations
- Pause task doesn't work in non-interactive CI/CD pipelines (use `-e` variable passing instead)
- SSH key file permissions need periodic cleanup when ansible user differs from file owner
- Test environment (servyy-test.lxd) not in standard prod inventory (intentional design)

## Related Decisions
- ADR-001: All infrastructure changes must go through Ansible (no manual server edits)
- ADR-003: Use gh-dash topic for repository discovery in opencode

## Alternatives Considered

### Alt A: Role-Based Removal (docker_remove_service role)
**Pros:** Follows existing pattern; reusable pattern  
**Cons:** More complex; adds abstraction for one-off operation  
**Decision:** Rejected - playbook is simpler for one-off operations; roles better for recurring patterns

### Alt B: Tag-Based Control (--skip-tags "service.{name}")
**Pros:** No inventory changes needed; uses existing tag infrastructure  
**Cons:** Harder to track in git; tags must be manually set per service; no single source of truth  
**Decision:** Rejected - inventory flags are more maintainable and explicit; creates clear source of truth in git

### Alt C: Separate undeploy.yml playbook
**Pros:** Mirrors deployment pattern; separation of concerns  
**Cons:** User must maintain two parallel playbooks; greater maintenance burden  
**Decision:** Rejected - single remove_service.yml simpler; deployment doesn't need corresponding undeploy

## Usage

### Remove a Service Permanently

**Step 1:** Remove from server
```bash
cd ansible
ansible-playbook plays/remove_service.yml -e "target_host=lehel.xyz"
# Prompts for service name and confirmation
# Removes: containers, volumes, service directory
```

**Step 2:** Disable in inventory & cleanup git
```bash
# Edit ansible/production: service_name: true → service_name: false
git rm -r {service}/
git add ansible/production
git commit -m "chore: remove {service} service"
git push origin master
```

**Step 3:** Deploy to apply changes
```bash
cd ansible && ./servyy.sh --limit lehel.xyz
# Service role skipped, no re-deployment
```

### Recovery

If service needs to be re-enabled:
```bash
# Edit ansible/production: service_name: false → service_name: true
git add ansible/production
git commit -m "chore: re-enable {service} service"
./servyy.sh --limit lehel.xyz
# Service will be redeployed
```
