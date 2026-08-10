# ADR-010: Resume an approved run by replaying its event log

- Status: accepted
- Date: 2026-08-09
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

A tool granted `requires_approval` parks the run: the call is validated, nothing is
executed, and the run stops in `awaiting_approval` (FR-E2). When an approver releases it,
the agent has to carry on from where it paused — execute the released action and reason
over its result.

But the object that was holding that conversation is gone. Parking and approving are
different HTTP requests, minutes or hours apart, possibly in different processes and
across a restart; [ADR-003](./003-custom-agent-runtime.md) deliberately keeps no
in-memory state worth recovering. So: where does a resumed run's prompt come from?

This is the checkpointing concern ADR-003 named as something we would own ourselves
("checkpoint serialization") now coming due.

## Decision Drivers

- **Reconstructability is already a requirement.** [ADR-008](./008-append-only-audit.md)
  says a run's full history must be derivable from events alone (FR-G1). If that is true,
  the transcript is already in the database and storing it again is duplication.
- **The resumed agent must see the conversation it paused in.** An agent that resumes
  against a subtly different prompt produces a plausible, wrong, and unreproducible
  decision — the failure mode a reviewer cannot catch.
- **Nothing may bypass the tool gateway** (golden rule 2), including the released call.
- **Ceilings are per run** (FR-B3, NFR-3). An approval must not hand the agent a second
  full budget or a second allowance of `max_steps`.

## Considered Options

- **Replay the transcript from the run's events** at resume time
- **Persist the message list** on the run row (or a `run_checkpoints` table) when parking
- **Re-run the agent from scratch** with the approval already granted

## Decision Outcome

Chosen option: **replay from the event log**. `app/runtime/transcript.py` rebuilds the
conversation from the run's own events — the system message from the pinned DNA, the run
input from `run.started`, and one assistant/user pair per **executed** `tool.called`
event. `AgentRuntime.resume_run` then executes the released call through the ordinary
gateway, appends its result, and re-enters the same loop.

Crucially, every message is built by a function the live loop calls too, so the live
transcript and the replayed one are one code path and cannot drift into two ideas of what
the agent was told.

Budget and step count are restored the same way — from the `runs` row and from
`model.called` events — so `max_cost_usd_per_run` and `max_steps` keep meaning "per run"
across the pause. The wall-clock timeout is deliberately *not* restored: it is measured
from the resume, because the hours a person took to answer their queue are not the agent
overrunning.

**Persisting the message list** was rejected as a second source of truth for something the
event log already holds. It would need its own schema versioning, and the day it disagreed
with the events, the trace and the agent's actual prompt would differ with nothing to say
which was right. **Re-running from scratch** was rejected outright: it re-spends the
budget, re-executes every read against a system of record whose state may have moved, and
makes the approval a decision about a run that no longer exists.

### Consequences

- Good: no new state to keep in sync, and the resumed prompt is *auditable* — what the
  agent sees after a resume is exactly what the log says happened, which is a stronger
  property than "we saved it correctly".
- Good: resuming needs no sticky process, so a run may park in one instance and resume in
  another. Horizontal scaling and restarts fall out for free.
- Bad: **correction turns are not replayed.** A schema violation and its one corrective
  turn (ADR-006) are not in the log as messages, so a run that paused after a correction
  resumes without it. Accepted deliberately: those turns are the platform talking about
  *formatting*, not facts about the case, and every fact the agent used is a tool result.
- Bad: the replay depends on the `tool.called` payload shape. A change to it is a change
  to how paused runs resume, which is why the payload is written and read in one module
  and covered by tests that resume a real run.
- Bad: a released call is re-validated against the *current* published DNA, so an approval
  granted while a grant was revoked is refused at the gateway rather than honoured. That
  is the intended reading of least privilege, but it does mean an approval is a permission
  to proceed, never a guarantee of execution — the resumed run fails closed with the
  gateway's reason code, and the trace says so.
