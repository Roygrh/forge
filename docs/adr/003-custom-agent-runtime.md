# ADR-003: Agent runtime = custom lightweight loop

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

The runtime interprets any valid DNA definition (FR-B1): a reasoning loop that calls
the LLM gateway, routes tool calls through the tool gateway, enforces budgets and
guardrails, externalizes state, and pauses/resumes across HITL approvals. Should it
be built on an orchestration framework (LangGraph, CrewAI) or as a custom loop?

## Decision Drivers

- Bounded scope: three agents, linear reason→act→observe loops with HITL pauses —
  no complex graph topologies.
- Governance is the product: budget enforcement, fail-closed escalation, and trace
  emission must be first-class in the loop, not wrapped around a framework.
- Contract purity: persisted artifacts (runs, traces, events) and APIs must contain
  zero framework types; the DNA schema is the only contract.

## Considered Options

- Custom lightweight loop (~few hundred lines)
- LangGraph
- CrewAI

## Decision Outcome

Chosen option: **custom lightweight loop**. At this scope the loop is small enough
to own outright, and every governance requirement (max steps, cost budgets, structured
outputs, escalation, resumable state) maps directly to explicit code — nothing hides
inside framework internals. It also demonstrates the architectural claim: frameworks
are replaceable implementation details *inside* the runtime boundary. Because no
framework type leaks into persisted artifacts or APIs, swapping the loop's internals
for LangGraph later would change no contract.

**When LangGraph would win**: genuinely complex graph topologies (dynamic branching,
parallel sub-agents, cycles with conditional edges) or checkpointing at scale, where
hand-rolled state machines become the larger liability. That threshold is documented
here deliberately — this is a scope decision, not a framework dismissal. CrewAI was
rejected outright: its role-based abstractions fight the declarative-DNA model.

### Consequences

- Good: every line of the control loop is auditable; guardrails are structural;
  no dependency churn from a fast-moving framework ecosystem.
- Bad: we own concerns frameworks give for free (retry plumbing, checkpoint
  serialization); acceptable at 3 agents, re-evaluated if topology needs grow.
- Bad: no community patterns to lean on when debugging loop behavior.
