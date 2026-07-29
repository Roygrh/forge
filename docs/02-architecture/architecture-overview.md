# Architecture Overview

This document narrates the C4 structure model in [`c4/workspace.dsl`](./c4/workspace.dsl).
Forge is one software system with three containers — a **Web App** (React SPA), a
**Backend API** (Python/FastAPI, which holds the platform), and **PostgreSQL 16**
([ADR-004](../adr/004-postgres-single-store.md)) — talking to three external systems:
LLM providers, the simulated MeridianERP, and simulated email intake.

The nine components inside the Backend API are best understood not one by one but as
**five conceptual layers**. The layers are a reading of the same model, not extra
boxes: each maps to concrete components in the component view.

## 1. Definition layer — *what an agent is*

The **DNA Registry** validates every agent definition against the DNA JSON Schema,
stores it, and versions it (semver). Nothing runs that the schema has not admitted —
the schema is the central contract, and fail-closed governance fields are `const`-locked
in it (see [`dna-README.md`](./dna-README.md)). This layer is the source of everything
the runtime is allowed to do: tools granted, knowledge reachable, budgets, guardrails.
Definitions and their lifecycle transitions are persisted in PostgreSQL.

## 2. Runtime layer — *how an agent acts*

The **Runtime Loop** is a custom reason/act/observe loop
([ADR-003](../adr/003-custom-agent-runtime.md)) — deliberately not a framework, so
that budget enforcement, fail-closed escalation, and trace emission are first-class
code rather than behaviour wrapped around someone else's engine. It interprets any
valid DNA (one engine, N agents), enforces `max_steps` and `timeout`, and pauses/resumes
across human approvals with all state externalized to the database.

Every model call leaves the loop through the **LLM Adapter Layer**
([ADR-005](../adr/005-llm-adapter-layer.md)): one `complete()` contract over provider
adapters, enforcing token and cost budgets and holding the *only* copy of the API keys.
Model output is schema-validated with one bounded retry, then escalation
([ADR-006](../adr/006-structured-outputs.md)) — malformed output never becomes an action.

## 3. Tools + knowledge layer — *what an agent can reach*

The **Tool Gateway** is the single, mandatory path from an agent to any external
system: MeridianERP and email intake are reachable *only* through it. It holds the
tool registry (typed in/out contracts), validates every call before execution, and
enforces per-agent least privilege and the `autonomous` / `requires_approval` /
`forbidden` autonomy level from the DNA. An unknown tool, invalid args, or missing
permission fails closed.

**Knowledge Retrieval** serves governed rules and policy documents via hybrid
semantic + lexical search (pgvector plus lexical matching, [ADR-004](../adr/004-postgres-single-store.md)),
applies the authority hierarchy (`sme_validated` > `policy_2023` > `policy_2019`), and
returns citations. Conflicts are surfaced, never silently averaged.

## 4. Governance — *cross-cutting, not a box*

Governance is not a component; it is a property distributed across the model. It shows
up as: policy enforcement inside the Tool Gateway; budget enforcement inside the LLM
Adapter Layer; schema-locked fail-closed defaults in the Definition layer; the
**Approval Service** (granular, expiring approvals that cancel and never auto-approve);
the **Circuit Breaker** (trips on error/cost thresholds and suspends the agent); the
publish gate in the **Eval Runner** (a version that fails its suite cannot ship); and
the **Event Store Writer**, which appends immutable events with no update/delete grant
([ADR-008](../adr/008-append-only-audit.md)) so that every decision is reconstructable.
Requirement families C, E, F and G ([requirements](../01-discovery/05-requirements.md))
land almost entirely in this layer.

## 5. Experience layer — *how humans work with it*

The **Web App** maps one-to-one onto three components: the catalog edits DNA through the
DNA Registry, the approval queue works through the Approval Service, and the trace viewer
reads run traces as projections of the append-only event log. Because the UI reads what
was actually recorded, "the screen shows exactly what happened" is true by construction
([ADR-008](../adr/008-append-only-audit.md)).

---

Physically, everything above ships as three container images plus seed data via Docker
Compose ([ADR-009](../adr/009-docker-compose-deployment.md)); the same images serve a
future cloud instance.

## Open questions

- **Read model vs. write model.** The Event Store Writer currently owns both the
  append path and the trace/lifecycle read projections. ADR-008 already flags the
  events table's dual audit/read duty as a known coupling; if UI read patterns diverge
  from the write shape, a distinct query/read-API component may need to split out. Left
  open deliberately — it is a scale threshold, not a v1 decision.
