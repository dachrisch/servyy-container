---
name: session-messaging
description: Use when coordinating work with another running opencode session on the same host - delegating infra changes, handing off tasks, requesting review, replying to inbox mail.
---

# Session Messaging

Directed messaging between independent top-level opencode sessions on the same host (`opencode.web` on `codey.lehel.xyz`). Parent↔subagent sessions stay native; this is for `Session A -> Session B` coordination.

## Tools (from `session-messaging.js` plugin)

| Tool | Purpose |
|------|---------|
| `session_register(name)` | Claim a kebab-case name, e.g. `bob-infra` |
| `session_list()` | Name → ID discovery (never guess UUIDs) |
| `session_send(to, text, mode?, thread?, reply_to?)` | `notify` (default, context-only) or `ask` (triggers turn) |
| `session_check(limit?)` | Read incoming `[from:*]` messages |

## Workflow

1. Register first: `session_register` with a goal-oriented name. Keep it for the session.
2. Discover: `session_list` before every `send`. Directory listing ≠ liveness.
3. Send:
   - `notify` (default): FYI, handoff complete, context. Target reads on next poll.
   - `ask`: only when you want the target to act now ("implement infra change Y").
   - Body must state: requested action, evidence (file/branch/commit refs), next action. Keep it short. No secrets/tokens.
   - Use `thread` to group, `reply_to` when answering.
4. Receive: call `session_check` at session start, before each user prompt, and before declaring done. Reply explicitly when the sender needs a result.

## Example

```text
A (alice-feat, implementing feature X):
  session_register(name=alice-feat)
  session_list()  # finds bob-infra
  session_send(to=bob-infra, mode=ask, thread=feat-x,
    text="Add traefik label in dontforget/compose for branch feat-x. Evidence: git/dontforget@abc. Next: reply notify when deployed on test.")

B (bob-infra):
  session_check()  # sees [from:alice-feat][thread:feat-x]
  ... implements ...
  session_send(to=alice-feat, mode=notify, thread=feat-x, text="Done, compose updated and test deploy green.")
```

## When NOT to use

- Parent spawning helpers: use native subagents / child sessions instead.
- Broadcast "I finished" with no addressee: use a handoff note, not a directed message.
- Need an answer right now from a busy session: mailbox queues but won't preempt; coordinate via the user instead.

## Common mistakes

- Sending before `register`/`list` (unknown sender, guessed UUID).
- Using `ask` for FYI (interrupts target's turn). Default to `notify`.
- Putting secrets in message text (registry + prompts are plaintext on host).
- Assuming delivery = read. Follow up with `session_check` / explicit reply.
