---
name: infrastructure-history-tracking
description: Auto-create and update history entries for service/Ansible work
---

# Infrastructure History Tracking Skill

Uses [Architecture Decision Records (ADR)](https://adr.github.io/) format to document infrastructure work systematically.

## Purpose

Ensure all **completed** infrastructure changes (service updates, Ansible modifications, deployments) are documented with context, results, and architectural decisions. Prevents ad-hoc work from being lost to history and creates a decision trail for future reference.

**⚠️ Key Principle:** History documents DONE work, not backlog or future plans. Each ADR captures one completed decision with its actual results and learnings. Future work gets its own new ADR when that work starts.

## Trigger

Use this skill when starting work on:
- Service deployments or undeployments
- Ansible playbook/role changes
- Infrastructure automation updates
- Docker service modifications
- Configuration management changes

## What to Include

✅ **DO Include:**
- Actual decisions made and why
- Completed work with real commit hashes
- Testing results (what passed, what failed and was fixed)
- Key learnings and discoveries
- Known issues/limitations of current solution
- Alternatives that were considered and rejected
- Related infrastructure decisions
- What surprised you during implementation

## What NOT to Include

❌ **DO NOT Include:**
- Future enhancements or improvements
- Backlog items or TODO lists
- Planned work that hasn't happened yet
- "Nice to have" features
- Speculative improvements
- Wishlist items for next iteration

If you think of improvements during work, create a NEW ADR later when that work actually starts. Don't clutter the completed work history with future plans.

## Workflow

### Phase 1: Work Planning (START)

When you begin infrastructure work:

1. **Assistant creates a history entry file:**
   ```
   history/YYYY-MM-DD_work-description.md
   ```

2. **Uses ADR template sections:**
   - Title/Status
   - Context (problem to solve)
   - Decision (what we'll do)
   - Consequences (positive/negative)
   - Testing Plan

3. **Example (starting phase):**
   ```markdown
   # ADR-004: Service Undeployment via Inventory Control
   
   **Date:** 2026-08-28  
   **Status:** Proposed  
   **Relates to:** ADR-001 (Infrastructure as Code)
   
   ## Context
   
   Currently, services can only be removed manually via SSH, creating:
   - Inconsistent state between git and servers
   - No audit trail of removals
   - Risk of re-deployment of removed services
   - Violates infrastructure-as-code principles
   
   We need a safe, automated, git-tracked way to decommission services.
   
   ## Decision
   
   Implement three-part system:
   1. Interactive Ansible playbook (remove_service.yml)
   2. Inventory dict structure (services_enabled with true/false flags)
   3. Pre-task filtering in user.yml
   
   This keeps all changes in git and prevents accidental re-deployment.
   
   ## Planned Consequences
   
   ### Positive
   - ✅ Services tracked in git history
   - ✅ Prevents re-deployment via inventory
   - ✅ Reversible (can re-enable)
   
   ### Negative/Tradeoffs
   - ⚠️ Inventory structure changes
   - ⚠️ New workflow to learn
   
   ### Implementation Plan
   
   **Files to modify:**
   - ansible/plays/remove_service.yml (NEW)
   - ansible/production (MODIFY)
   - ansible/plays/user.yml (MODIFY)
   - CLAUDE.md (MODIFY)
   
   **Testing plan:**
   - Verify playbook syntax
   - Test on servyy-test.lxd
   - Deploy to production (code.lehel.xyz)
   - Verify container running and provisioning works
   ```

4. **DO NOT commit the plan yet** - it's a working document

### Phase 2: Work Execution

Continue with normal development. Update the plan file as you learn:
- Actual steps taken (if different from planned)
- Issues encountered and solutions
- Commits made
- Test results

### Phase 3: Work Completion (FINISH)

When work is done:

1. **Convert ADR from Proposed → Accepted:**
   - Change `Status: Proposed` → `Status: Accepted`
   - Update "Consequences" with actual (not planned) results
   - Add "Implementation Details" subsection with:
     - Actual files modified
     - Git commits (hash - message format)
     - Testing & Verification (what actually passed)
     - Key Learnings (discoveries, gotchas, patterns)
     - Known Issues (current limitations only - NOT future enhancements)
   - Add "Alternatives Considered" section showing what you evaluated
   - Add "Related Decisions" if this ADR depends on others
   
   **⚠️ Important:** History entries document COMPLETED work only. Do not include future plans or enhancements - those belong in separate ADRs when the work starts.

2. **Example final entry (ADR format):**
   ```markdown
   # ADR-004: Service Undeployment via Inventory Control
   
   **Date:** 2026-08-28  
   **Status:** Accepted  
   **Relates to:** ADR-001 (Infrastructure as Code)
   
   ## Context
   
   Previously, services could only be removed manually via SSH, creating inconsistency and git tracking issues. We need a safe, repeatable way to decommission services through automation while preventing accidental re-deployment.
   
   ## Decision
   
   Implement a three-part Ansible-based system:
   1. Interactive `remove_service.yml` playbook for safe removal
   2. Inventory restructuring to `services_enabled` dict with enable/disable flags
   3. Pre-task in user.yml that automatically filters based on enabled status
   
   This keeps all changes in version control and prevents services from being re-deployed after removal.
   
   ## Consequences
   
   ### Positive
   - ✅ All service removals tracked in git with full history
   - ✅ Prevents accidental re-deployment via inventory flags
   - ✅ Interactive confirmation prevents mistakes
   - ✅ Backward compatible (all services default to enabled)
   - ✅ No manual server operations needed
   - ✅ Reversible (re-enable by changing flag)
   
   ### Negative / Tradeoffs
   - ⚠️ Added complexity to inventory structure (dict vs list)
   - ⚠️ Pause task doesn't work in non-interactive CI mode
   - ⚠️ Requires git workflow discipline (can't manually SSH to fix)
   
   ### Implementation Details
   
   **Files Modified:**
   - `ansible/plays/remove_service.yml` (NEW)
   - `ansible/production` (services → services_enabled dict)
   - `ansible/plays/user.yml` (+pre-task for filtering)
   - `CLAUDE.md` (+removal workflow section)
   
   **Commits:**
   - 9c5edf8 docs: add history entry
   - 374a0c5 fix: use pause task instead of vars_prompt
   - 4e7b6d8 feat: implement service undeployment workflow
   
   **Testing & Verification:**
   ✅ Playbook syntax verified with target_host parameter  
   ✅ Manual removal tested on servyy-test.lxd  
   ✅ Inventory control verified on code.lehel.xyz deployment  
   ✅ Only opencode deployed with tag filtering  
   ✅ Container running and healthy  
   ✅ gh-dash topic discovery confirmed in logs  
   
   **Key Learnings:**
   1. **vars_prompt limitation** - Cannot reference undefined variables; switch to pause task for two-step prompts
   2. **Permission handling** - Files written by Ansible with root ownership need pre-cleanup for subsequent runs
   3. **Inventory as control** - Dict structure enables powerful conditional logic vs list-only approach
   4. **Role invocation filtering** - Tags work at role inclusion level, not just task level
   5. **Backward compatibility** - Dict-to-list conversion maintains 100% compatibility with existing conditions
   
   ### Known Issues & Limitations
   - Pause task doesn't work in non-interactive CI/CD pipelines (must use `-e` variable passing)
   - SSH key file permissions need periodic cleanup when ansible user differs from file owner
   - Test environment (servyy-test.lxd) not in standard prod inventory (intentional)
   
   ## Related Decisions
   - ADR-001: All infrastructure changes must go through Ansible (no manual server edits)
   - ADR-003: Use gh-dash topic for repository discovery
   
   ## Alternatives Considered
   
   ### Alt A: Role-Based Removal
   Pros: Follows existing pattern  
   Cons: More complex, less flexible for one-off removals  
   **Rejected**
   
   ### Alt B: Tag-Based Control (--skip-tags)
   Pros: No inventory changes needed  
   Cons: Harder to track in git, harder to maintain  
   **Rejected**
   
   ### Alt C: Separate undeploy.yml
   Pros: Mirrors deployment pattern  
   Cons: User must maintain two parallel files  
   **Rejected**
   ```

3. **Commit the final history entry** with message referencing work done

## ADR Sections (Required)

Following [Architecture Decision Records](https://adr.github.io/) format:

### Title
**Format:** `ADR-###: Concise decision title`  
Uniquely identifies the decision in history

### Status
- `Proposed` - Under consideration/in progress
- `Accepted` - Completed and approved
- `Deprecated` - No longer used but kept for reference
- `Superseded` - Replaced by another ADR (link it)

### Context
**Most important for future readers.** Explain:
- What problem are we solving?
- Why is this a problem?
- What constraints exist?
- What's the current pain point?

### Decision
State WHAT we decided and WHY:
- What approach are we taking?
- Why is this better than alternatives?
- What tradeoffs are we making?

### Consequences
**Most important for learning.** Include:

**Positive:**
- ✅ What becomes easier/better?
- ✅ What problems does this solve?
- ✅ What capabilities does this enable?

**Negative/Tradeoffs:**
- ⚠️ What becomes harder?
- ⚠️ What new constraints are introduced?
- ⚠️ What maintenance burden is added?

**Implementation Details:**
- Files modified (with type: NEW/MODIFY)
- Git commits (hash - message)
- Testing results (what was verified)
- Key learnings (discoveries during implementation)
- Known issues (current limitations only)

### Related Decisions
Link to ADRs this decision builds on or affects

### Alternatives Considered
For each alternative not chosen:
- Pros (why it looked good)
- Cons (why we rejected it)
- Decision (why final choice was better)

## Benefits

1. **Searchable History** - Find past decisions and context via git log
2. **Onboarding** - New team members understand infrastructure evolution
3. **Learnings Captured** - Avoid repeating mistakes
4. **Decision Trail** - Why was something done this way?
5. **Patterns** - Identify common approaches and anti-patterns
6. **No Backlog Clutter** - History stays clean, focused on completed work

## When to Use This Skill

✅ **Always use for:**
- Ansible playbook/role changes
- Service deployments/updates
- Infrastructure automation additions
- Major configuration changes
- Troubleshooting/fixes that took iteration

❌ **Skip for:**
- One-line documentation fixes
- Typo corrections in configs
- Simple dependency updates
- Quick log checks or status verifications

## Tips

1. **Start early** - Create the ADR on day 1, before you code
2. **Update incrementally** - Add learnings as you discover them, don't wait until the end
3. **Capture surprises** - Things that didn't work as expected are the most valuable learnings
4. **Link related work** - Reference other ADRs that are connected
5. **Be specific** - "fixed bug" is less useful than "fixed race condition in service startup due to missing network dependency"
6. **No backlog** - Don't add future plans; create new ADRs when that work starts

---

**Always ask:** "What would I want to know about this in 6 months?"  
**Answer in:** The history ADR  
**Remember:** History is for COMPLETED work, not backlog planning.
