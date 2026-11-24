# AGENTS.md Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** replace `CLAUDE.md` with a complete AGENTS.md hierarchy and fix the per-directory coverage gaps.

**Architecture:** keep the root file as the entry point, distribute component-specific operational knowledge into eight new subdirectory guides, move Loki/fail2ban recipes into the existing monitor guide, repoint all references, then verify no content or links are lost.

**Tech Stack:** Markdown, git, git-crypt, relative links.

---

### Task 1: Add the eight new subdirectory guides

**Files:**
- Create: `ansible/AGENTS.md`, `architecture/AGENTS.md`, `claude-hub/AGENTS.md`, `opencode/AGENTS.md`, `hetzner/AGENTS.md`, `scripts/AGENTS.md`, `docs/AGENTS.md`, `searxng/AGENTS.md`

**Step 1:** Write each guide with its mapped CLAUDE.md sections verbatim plus a short purpose header and links to root/history. Use the exact section text so no operational detail is lost.

**Step 2:** Run `grep -c '^#' <file>` on each: every guide must have a title and at least one section.

**Step 3:** Commit: `docs: add missing subdirectory AGENTS.md guides`

### Task 2: Move Loki/fail2ban recipes into monitor/AGENTS.md

**Files:** Modify `monitor/AGENTS.md`

**Step 1:** Append the "Verifying Container Labels for Loki Queries", "Testing Loki Queries", "Loki Query Issues" and "fail2ban Issues" content from CLAUDE.md as a new `## Querying logs and checking bans` section.

**Step 2:** Verify the credential pointer (`monitor_remote_auth.loki_password`) and tenant ID are present.

**Step 3:** Commit: `docs: move Loki and fail2ban recipes into monitor guide`

### Task 3: Merge CLAUDE.md into root AGENTS.md

**Files:** Modify `AGENTS.md`

**Step 1:** Insert a `## Subdirectory guides` index after the intro, linking all 17 guides.

**Step 2:** Append the mapped repo-wide CLAUDE.md sections, demoting `###` headings only where nesting requires it. Shorten the claude-hub table row to a pointer. Add pointers where content moved (Molecule tests, cleanup automation, LeagueSphere docs, Loki recipes).

**Step 3:** Trim root's Molecule subsection to one line + pointer to `ansible/AGENTS.md`.

**Step 4:** Spot-check heading list and commit: `docs: absorb CLAUDE.md into AGENTS.md`

### Task 4: Remove CLAUDE.md and repoint references

**Files:** Delete `CLAUDE.md`; modify every file that references it.

**Step 1:** `grep -rln 'CLAUDE\.md' --exclude-dir=.git .` to enumerate references.

**Step 2:** Repoint each to the new owner file (`AGENTS.md` or the relevant subdir guide), except the history entry where the old name is part of the record.

**Step 3:** `git rm CLAUDE.md` and commit: `docs: remove CLAUDE.md and repoint references`

### Task 5: History entry and plan cleanup

**Files:** Create `history/2026-11-24_agents-md-consolidation.md`; delete both plan docs.

**Step 1:** Write the history entry (problem, mapping, files, verification).

**Step 2:** Delete `docs/plans/2026-11-24_agents-md-consolidation*.md` per `history/AGENTS.md`.

**Step 3:** Commit: `docs: record AGENTS.md consolidation`

### Task 6: Final verification

**Step 1:** `grep -rn 'CLAUDE\.md' --exclude-dir=.git .` — only the history entry may match.

**Step 2:** Relative-link check over all changed `*.md` files.

**Step 3:** Heading-mapping check: every CLAUDE.md heading appears in exactly one destination file (from git show of the deleted file).

**Step 4:** `git status --short` — only intended changes.
