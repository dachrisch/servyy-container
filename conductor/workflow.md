# Project Workflow

## Guiding Principles

1. **The Plan is the Source of Truth:** All work MUST be tracked in `plan.md`.
2. **GitOps & IaC:** All changes MUST be defined in this repository and applied via Ansible. Manual server edits are forbidden.
3. **Testing First (Test-Driven Infrastructure):**
   - All changes MUST be verified on `servyy-test.lxd` before production.
   - Verification includes service health, log availability in Loki, and connectivity.

4. **History Tracking:** EVERY major change or infrastructure migration MUST be documented in `history/YYYY-MM-DD_description.md`.
5. **Observability as a Requirement:** Services are only complete when logs are in Loki and metrics are in Prometheus.
6. **Secret Management:** Secrets MUST be managed via `git-crypt`. Never commit plain-text secrets.

## Task Workflow

All tasks follow a strict lifecycle, utilizing specialized agents where appropriate (Master, Analyst, Tester).

### Infrastructure Task Workflow

1. **Select Task:** Choose the next available task from `plan.md`.

2. **Mark In Progress:** Edit `plan.md` and change status from `[ ]` to `[~]`.

3. **Branch & Agent Initialization:**
   - Create a feature branch: `claude/feature-name` (or current agent prefix).
   - If the task is complex, invoke the `service-requirements-analyst` (Analyst agent) to refine the technical specification.
   - Setup task files (e.g., `ansible/plays/roles/[role]/tasks/[task].yml`).

4. **Service Definition & User Loop:**
   - Define the service behavior, ports, and external access (Traefik).
   - Define the verification loop (e.g., "Check `https://service.lehel.xyz`, verify Loki label `{container='service'}`).
   - **PAUSE** for user feedback on the service definition.

5. **Ansible Planning & Validation:**
   - Plan Ansible changes (tags, roles, variable overrides).
   - Use `ansible-lint` to validate the plan.
   - Present the plan (e.g., "I will update `user.yml` with tag `service-xyz`").
   - **PAUSE** for user validation.

6. **Implementation & Test Verification:**
   - Implement roles/tasks and `docker-compose.yml`.
   - Deploy to test environment: `cd ansible && ./servyy-test.sh --tags [tag]`.
   - Iterate until verification on `servyy-test.lxd` passes.

7. **Verification on servyy-test:**
   - Use `service-tester` (Tester agent) to perform automated verification of the test deployment.
   - Verify logs: `docker logs [service]` on the test container.

8. **Production Approval & Documentation:**
   - Present verification results from `servyy-test.lxd`.
   - **Create History Entry:** Write the migration/change details to `history/`.
   - **PAUSE** and await explicit "Approved for Production" from the user.

9. **Production Rollout:**
   - Execute production deployment: `cd ansible && ./servyy.sh --limit lehel.xyz --tags [tag]`.
   - Perform immediate post-deploy health check.

10. **Finalize Task:**
    - Stage changes and commit (following Conventional Commits).
    - Attach task summary and verification logs via `git notes`.
    - Update `plan.md` status to `[x]` with commit SHA.

### Phase Completion & Checkpointing

**Trigger:** Completion of a Phase in `plan.md`.

1. **Checkpoint Commit:** `conductor(checkpoint): End of Phase: [Phase Name]`.
2. **Verification Report:** Attach a summary of all history entries and test results created during the phase via `git notes`.
3. **Record SHA:** Update `plan.md` with the checkpoint SHA.

## Development Commands

### Environment Setup
```bash
# Unlock secrets
git-crypt unlock
# Install dependencies
cd ansible && pip install -r requirements.txt && ansible-galaxy install -r requirements.yml
```

### Testing & Validation
```bash
# Linting
ansible-lint ansible/
# Deploy to Test Environment
cd ansible && ./servyy-test.sh --tags [tags]
```

### Deployment
```bash
# Production (ONLY after approval)
cd ansible && ./servyy.sh --limit lehel.xyz --tags [tags]
```

## Definition of Done
- [ ] Ansible code passes `ansible-lint`.
- [ ] Successfully deployed and verified on `servyy-test.lxd`.
- [ ] Logs appearing in Loki; metrics in Prometheus (if applicable).
- [ ] `history/` documentation created/updated.
- [ ] User approval received for production.
- [ ] Production deployment successful.
- [ ] `plan.md` updated and `git notes` attached.
