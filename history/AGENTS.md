# history/ — change records

One file per significant change: `history/YYYY-MM-DD_short-description.md`. It records the
problem, what was done, files changed, deployment results and verification commands. It is
the durable record; plans are not.

## Plans are temporary: remove them when the job is done

Plans (`docs/plans/`, `docs/superpowers/plans|specs/`, a `conductor/` track, or any other
plan/spec file) exist only while the work is in flight. In the change that closes the job:

1. **Write or finish the history entry** for the work.
2. **Move what is still needed into it** — decisions that code comments cite, runbooks for
   work that is deferred or recurring, dated follow-ups. Everything else stays in git
   history only. A runbook that will be run again (a release or import procedure) goes
   next to the service instead, e.g. `moodle/release-runbook.md`.
3. **Delete the plan file(s).**
4. **Repoint references.** Code, compose files, `AGENTS.md` and `docs/` must point at the
   history entry, never at a deleted plan (`git grep -n "docs/plans/"` must come back
   empty outside `history/`).
5. In older history entries, keep the reference to the plan and mark it
   `(removed YYYY-MM-DD, in git history)`, instead of rewriting the record.

A plan left behind after its job is done goes out of date silently, and the next agent
treats it as current.
