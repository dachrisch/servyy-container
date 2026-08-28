---
name: infrastructure-history-tracking
description: Auto-create and update history entries for service/Ansible work
---

# Infrastructure History Tracking Skill

## Purpose

Ensure all infrastructure changes (service updates, Ansible modifications, deployments) are documented with context, results, and learnings. Prevents ad-hoc work from being lost to history.

## Trigger

Use this skill when starting work on:
- Service deployments or undeployments
- Ansible playbook/role changes
- Infrastructure automation updates
- Docker service modifications
- Configuration management changes

## Workflow

### Phase 1: Work Planning (START)

When you begin infrastructure work:

1. **Assistant creates a history plan file:**
   ```
   history/YYYY-MM-DD_work-description.md
   ```

2. **Plan includes template sections:**
   - Summary (1-2 sentences)
   - Problem/Goal
   - Approach (steps planned)
   - Related Files (what will be modified)
   - Expected Outcome
   - Testing Plan

3. **Example:**
   ```markdown
   # Service Undeployment Workflow
   **Date:** 2026-08-28  
   **Status:** 🔄 In Progress
   
   ## Summary
   Implementing Ansible-based service removal with inventory control.
   
   ## Problem
   No dedicated undeployment workflow; services removed manually.
   
   ## Planned Approach
   1. Create remove_service.yml playbook
   2. Restructure inventory to services_enabled dict
   3. Add filtering pre-task to user.yml
   4. Document in CLAUDE.md
   
   ## Related Files
   - ansible/plays/remove_service.yml (NEW)
   - ansible/production (MODIFY)
   - ansible/plays/user.yml (MODIFY)
   - CLAUDE.md (MODIFY)
   
   ## Testing Plan
   - Verify playbook syntax
   - Test on servyy-test.lxd
   - Deploy to production (code.lehel.xyz)
   - Verify container running
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

1. **Convert plan to final history entry:**
   - Change `Status: 🔄 In Progress` → `Status: ✅ Complete & Tested`
   - Add "Commits" section with actual git hashes
   - Add "Testing & Verification" with real results
   - Add "Key Learnings" section (what surprised you, what to remember)
   - Keep "Related Files" updated
   - Add "Known Issues & Notes" if applicable

2. **Example final entry:**
   ```markdown
   # Service Undeployment Workflow
   **Date:** 2026-08-28  
   **Status:** ✅ Complete & Tested
   
   ## Summary
   Implemented production-ready service undeployment system with Ansible.
   
   ## Problem Solved
   Previously no safe way to remove services; manual operations created inconsistency.
   
   ## Solution Implemented
   Three-part system: removal playbook + inventory control + automatic filtering
   
   ## Commits
   - 9c5edf8 docs: add history entry
   - 374a0c5 fix: use pause task instead of vars_prompt
   - 4e7b6d8 feat: implement service undeployment workflow
   
   ## Testing & Verification
   ✅ Syntax verified
   ✅ Tested on test environment
   ✅ Production deployment successful
   ✅ Container running and healthy
   
   ## Key Learnings
   1. vars_prompt can't reference undefined variables - use pause task instead
   2. Permission issues with ansible-written files need pre-cleanup
   3. Inventory control is powerful for preventing unwanted deployments
   4. Tag filtering works at role invocation level
   
   ## Known Issues
   - Pause task doesn't work in non-interactive CI mode
   - SSH key permissions need occasional cleanup
   
   ## Future Enhancements
   - Add CI checks to prevent deploying disabled services
   - Service lifecycle dashboard in Grafana
   ```

3. **Commit the final history entry** with message referencing work done

4. **Delete the plan file** (git rm) if it was committed separately, or just replace it in place

## Key Sections to Always Include

### Summary
1-2 sentences of what was accomplished

### Problem / Goal
What was the pain point or objective?

### Solution Implemented
What approach was taken and why?

### Commits
List all git commits with hashes and messages

### Testing & Verification
- What was tested?
- What were the results?
- Evidence of success (logs, screenshots, metrics)

### Key Learnings
**Most important section.** Capture:
- Unexpected behaviors discovered
- Gotchas and workarounds
- Patterns that worked well
- Things to remember for next time
- Why certain decisions were made

### Known Issues & Notes
- Limitations of the implementation
- Future improvement ideas
- Edge cases not handled

### Related Features
Link to other interconnected work or infrastructure components

## Benefits

1. **Searchable History** - Find past decisions and context via git log
2. **Onboarding** - New team members understand infrastructure evolution
3. **Learnings Captured** - Avoid repeating mistakes
4. **Decision Trail** - Why was something done this way?
5. **Status Tracking** - See what's in progress vs. complete
6. **Patterns** - Identify common approaches and anti-patterns

## Template

Copy this template when starting infrastructure work:

```markdown
# [Work Title]
**Date:** YYYY-MM-DD  
**Status:** 🔄 In Progress

## Summary
[1-2 sentences of what this accomplishes]

## Problem / Goal
[What problem are we solving? What's the objective?]

## Planned Approach
[Steps you plan to take]

## Related Files
[Files that will be created/modified]

## Testing Plan
[How will you verify this works?]

---

## Actual Approach
[What you actually did, if different from plan]

## Commits
[Hash - message format]

## Testing & Verification
✅ [What passed]
✅ [What passed]
⚠️ [What had issues]

## Key Learnings
1. [Thing 1 you learned]
2. [Thing 2 you learned]
3. [Pattern to remember]

## Known Issues & Notes
- [Issue 1]
- [Future enhancement]

## Related Features
- [Link to related work]
```

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

1. **Start early** - Create the plan file on day 1, before you code
2. **Update incrementally** - Add learnings as you discover them, don't wait until the end
3. **Capture surprises** - Things that didn't work as expected are the most valuable learnings
4. **Link related work** - Reference other history entries that are connected
5. **Be specific** - "fixed bug" is less useful than "fixed race condition in service startup due to missing network dependency"
6. **Include error messages** - Future you will search for error text

## Example Usage in This Conversation

At START:
```
claude> I'll use infrastructure-history-tracking to plan this work
[Creates: history/2026-08-28_service-undeployment-workflow.md with plan]
```

During WORK:
```
Updated history entry with:
- Actual commits (4e7b6d8, 374a0c5, 9c5edf8)
- Testing results (verified on code.lehel.xyz)
- Learning: vars_prompt limitation with undefined variables
```

At FINISH:
```
Final history entry committed with full results and learnings
```

---

**Always ask:** "What would I want to know about this in 6 months?"  
**Answer in:** The history entry
