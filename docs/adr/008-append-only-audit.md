# ADR-008: Audit = append-only events table

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Compliance requires that every automated decision be reconstructable and that the
audit trail be tamper-evident (FR-G1, FR-G2): who/what did what, when, citing which
rules. An audit log that application code can UPDATE is not an audit log.

## Decision Drivers

- Immutability as a database property, not an application convention: the compliance
  stakeholder's requirement is "cannot be edited", not "we promise not to".
- Reconstructability: a run's full history — model calls, tool calls, rules applied,
  approvals, state transitions — must be derivable from events alone.
- Single store (ADR-004): the mechanism must live in PostgreSQL.

## Considered Options

- Append-only events table; application role granted INSERT/SELECT only
- Mutable state tables + trigger-based history/audit tables
- External append-only log (e.g., Kafka topic)

## Decision Outcome

Chosen option: **append-only events table** in PostgreSQL. The application database
role has **no UPDATE or DELETE grants** on it — immutability is enforced by the
grant system, out of reach of application bugs. Every state transition and every
agent decision is recorded as an event (typed payload, actor, timestamp, run/agent
refs). The UI reads project state **from events where practical** (approval queue,
trace viewer, lifecycle history); conventional relational tables remain for current
state that is queried heavily (agent definitions, run status), always written in the
same transaction as their event.

Trigger-based history captures changes but makes the mutable table primary and the
audit an afterthought — inverted priorities for this product. Kafka contradicts
ADR-004's single-store decision at demo scale.

### Consequences

- Good: tamper-evidence is structural; the trace viewer is a projection of events,
  so "the UI shows exactly what happened" is true by construction.
- Bad: dual-write (state row + event) must stay in one transaction — a discipline
  point covered by code review and tests, since drift would be silent.
- Bad: corrections require compensating events, never edits; event schema changes
  need versioned payloads. Table growth needs eventual partitioning (thresholds in
  ADR-004).

## Amendment — Phase 3.1, recorded at 6.2 (2026-08-26)

The decision stands, and the mechanism gained a second layer when it was implemented.
The grant alone — `INSERT`/`SELECT` only for the application role — is not enforcement
in the shipped stack, because PostgreSQL exempts a table's **owner** from its own grants
and the demo connects as the owner for operational simplicity. So the initial migration
(`src/backend/alembic/versions/20260729_0001_initial_schema.py`) installs both: the grants
for a dedicated `forge_app` role, *and* a trigger (`forge_events_are_append_only`) that
raises on `UPDATE`, `DELETE` and `TRUNCATE` for every role, owner included.
`tests/test_events_append_only.py` proves each layer, and the test suite runs the real
migration rather than `create_all` precisely so that this guarantee is tested and not
assumed. The claim in the title — immutability as a database property, not an
application convention — is therefore true for the connection the platform actually uses.
