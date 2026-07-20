# Forge — Project Charter

> **A governed agent factory, demonstrated with accounts-payable automation.**
> Agents are configuration artifacts, not code artifacts. Governance is structurally embedded, not bolted on.

| | |
|---|---|
| **Project name** | Forge |
| **Type** | Portfolio / demonstration platform |
| **Author** | Jorge Enrique Quiroz — Solutions Architect |
| **Status** | Phase 0 closed · Phase 1 (Discovery) in progress |
| **Version** | 1.0 — decisions frozen |

---

## 1. Vision

Forge is a miniature **enterprise agent platform**: a system where business-domain agents are defined declaratively (the agent "DNA"), executed by a single runtime, and governed by design — least-privilege tools, human-in-the-loop approvals, evaluation gates before publishing, and full traceability of every decision.

It is demonstrated end-to-end with one realistic vertical: **accounts-payable invoice processing** for a simulated mid-market client, *Meridian Supply Co.* — including the capture of the tacit business rules that live in people's heads, turned into governed, versioned knowledge.

Forge is deliberately **small in surface and honest in depth**: three agents, one tenant (with multi-tenant structure prepared), every architectural layer real.

## 2. Objectives

1. **Demonstration asset**: a repository + live demo + architecture documentation that a technical or non-technical evaluator can walk through in ~15 minutes and understand both the design judgment and the execution ability behind it.
2. **Deep practice**: every architectural claim (declarative DNA, runtime, tool gateway, authority-ranked knowledge, HITL, evals, fail-closed behavior) exists as working code, not slides.
3. **Reusable foundation** for future work beyond this demonstration.

## 3. Scope

### In scope
- Declarative agent definition (JSON Schema — the DNA) + versioning
- Single runtime interpreting N agent definitions (reasoning loop, tool calls, state externalized)
- Tool gateway: registry, typed contracts, least privilege, autonomy levels, fail-closed
- Knowledge layer: ingestion of client policies (with deliberate version conflicts), hybrid retrieval, authority hierarchy, citations
- Tacit-knowledge capture: documented SME interviews → explicit, versioned rules (highest authority source)
- Human-in-the-loop: approval queue with UI, granular approvals, expiring (fail-closed) timeouts
- Evaluation suite: ~20 real cases, runnable with one command, acting as a publish gate
- Observability: per-run traces visible in UI, basic metrics, simple circuit breaker
- Agent lifecycle: create, publish (gated), suspend, rebuild
- Minimal catalog UI for creating/operating agents without writing code
- Deployment: Docker Compose (on-premise story) + one low-cost public instance

### Out of scope (explicit)
- Operational multi-tenancy (structure prepared, single tenant active)
- Enterprise auth/SSO (simple login only) · High availability · Model fine-tuning
- More than one business vertical · Production-grade UI polish

## 4. Stakeholders

**Real:**
| Stakeholder | Interest |
|---|---|
| Jorge (architect/builder) | Demonstrate seniority with bounded effort |
| Axsys — product/technology evaluator | "Can this person solidify our architecture and ship it?" |
| Axsys — non-technical evaluator | Understand the value in 10 minutes (demo script + UI, not terminals) |

**Simulated (Meridian Supply Co.)** — full profiles in `01-discovery/02-stakeholders.md`:
CFO · AP Manager (owner of tacit rules) · AP Analyst (HITL approver) · Compliance Officer · IT Director.

## 5. Success criteria

- Live demo **< 10 minutes**: create an agent from the catalog by editing its DNA → process invoices → one HITL approval → one guardrail block → inspect the full trace of every decision.
- Evaluation suite runs with **one command**; an agent version cannot be published if it fails its suite.
- Complete C4 architecture documentation (Structurizr DSL) + ADRs.
- README understandable by a non-technical reader.

## 6. Constraints

Single builder, off-hours · API budget minimized (economical models by default, routing by task — consistent with the platform's own thesis) · Free or near-free infrastructure · Portable by design (containers).

## 7. Frozen decisions (Phase 0)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D-01 | Business vertical | **Accounts payable / invoice approval** | Matches the exact example the target audience uses; money makes governance visibly necessary; rich tacit rules; synthetic data easy to generate |
| D-02 | Architecture diagrams | **Structurizr DSL (C4 model) + Mermaid (behavior)** | Single source of truth for structure; GitHub-native rendering for sequences/flows |
| D-03 | Decision log format | **ADRs (MADR format)** | Documents judgment, not just outcomes |
| D-04 | Repository language | **English** | The audience evaluates in English |
| D-05 | Simulated client | **Meridian Supply Co.** (mid-market industrial distributor) | Believable AP volume and pain; low AI maturity = ideal governed-AI story |

## 8. Phase plan

| Phase | Content | Key deliverables |
|---|---|---|
| 0 | Planning | This charter |
| 1 | Discovery | Client profile · stakeholders · interview notes · **tacit rules doc** · requirements (MoSCoW) · eval cases (defined *before* building) |
| 2 | Architecture | C4 model (Structurizr DSL) · sequence diagrams (Mermaid) · **DNA JSON Schema v1** · OpenAPI contracts · data model · ADRs |
| 3 | Walking skeleton | One trivial agent end-to-end through every layer |
| 4 | Iterations | 4.1 AP agents + simulated ERP tools · 4.2 Governance I (permissions, limits, fail-closed) · 4.3 Knowledge (authority, conflicts, citations) · 4.4 HITL · 4.5 Evals as publish gate · 4.6 Observability + circuit breaker |
| 5 | Deployment | Docker Compose + public instance |
| 6 | Demo packaging | 10-min demo script (technical & non-technical) · README · backup video · seeded story data |

## 9. Top risks

| Risk | Mitigation |
|---|---|
| Scope creep ("one more feature") | Every iteration ends demoable; out-of-scope list is binding |
| Demo looks like a toy | Depth over breadth: fewer features, each one real (true HITL beats ten mocks) |
| API costs | Economical models by default; routing; strict budgets in every agent DNA |
| Time interruptions | Phases 1–2 are writing/design (fast with AI assistance); code iterations independently shippable |
