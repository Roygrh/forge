# Requirements — Forge (v1.0)

Prioritization: **MoSCoW** — `M` Must · `S` Should · `C` Could · `W` Won't (this version).
Every requirement traces to a stakeholder (see `02-stakeholders.md`) — governance features exist because someone demands them, not by fashion.

## A. Platform — agent definition & catalog

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-A1 | Agents are defined as declarative JSON documents validated against a published **DNA JSON Schema** (identity+version, instructions, tools+autonomy, knowledge refs, model+budgets, guardrails, evals ref) | M | Thesis |
| FR-A2 | Catalog UI: create/edit an agent by editing its definition through forms + raw JSON view; no code involved | M | Rosa, low AI maturity |
| FR-A3 | Definitions are versioned (semver); any historical run references the exact version that produced it | M | Dana, Priya |
| FR-A4 | Agent lifecycle: draft → published (eval-gated) → suspended → rebuilt; visible state transitions | M | Jeff's "start/stop/destroy/rebuild" |
| FR-A5 | Instruction blocks reusable across agents (inheritable policy/tone blocks) | S | DRY |

## B. Platform — runtime

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-B1 | Single runtime interprets any valid definition (one engine, N agents) | M | Thesis |
| FR-B2 | Run state externalized (DB); runs can be inspected, resumed after approval, and reproduced | M | Kevin, Dana |
| FR-B3 | Hard limits per run enforced from DNA: max steps, token budget, cost budget, timeout | M | Cost + Priya |
| FR-B4 | Structured outputs: model responses validated against schemas; invalid → bounded retry with feedback | M | Consistency |

## C. Platform — tool gateway

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-C1 | All tool calls pass through a single gateway; agents cannot reach systems directly | M | Priya, Tom |
| FR-C2 | Tool registry: typed contracts (JSON Schema in/out); gateway validates every call pre-execution | M | Safety |
| FR-C3 | Per-agent least privilege from DNA; autonomy level per tool: `autonomous` / `requires_approval` / `forbidden` | M | Priya |
| FR-C4 | Simulated MeridianERP tools: read_invoice, match_po, get_vendor, get_receipts, approve_invoice, schedule_payment, request_info_from_vendor | M | Domain |
| FR-C5 | Fail-closed: unknown tool, invalid args, missing permission, or policy doubt → do not execute, escalate | M | Priya |

## D. Knowledge layer

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-D1 | Ingest policy documents with metadata: owner, date, **authority level** | M | Rosa's "the PDF is wrong" |
| FR-D2 | Authority hierarchy applied at retrieval: `sme_validated` > `policy_2023` > `policy_2019`; conflicts resolved or surfaced, never silently averaged | M | Q6 thesis |
| FR-D3 | Hybrid retrieval (semantic + lexical) — exact terms (vendor names, invoice numbers) must hit | M | Domain |
| FR-D4 | Every agent answer/decision cites sources (rule IDs, document+section) | M | Dana, Priya |
| FR-D5 | Conflict detection logs a remediation item for the knowledge owner | S | Living-product principle |

## E. Human-in-the-loop

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-E1 | Approval queue UI: proposed action + agent reasoning + evidence (invoice, PO, fired rules) side by side | M | Kevin's <1-minute decision |
| FR-E2 | Granular approval: one decision covers exactly one action instance with its parameters | M | Priya |
| FR-E3 | Approvals expire (configurable SLA); expiry cancels — never auto-approves | M | Priya, fail-closed |
| FR-E4 | Every approve/reject recorded with actor, timestamp, and optional note | M | Audit |
| FR-E5 | Autonomy-promotion report: approval rates per action category, suggesting candidates for autonomy upgrade (applied only as a new DNA version) | S | Rosa's fatigue risk |

## F. Evaluation & publish gate

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-F1 | Eval suite: the 20 cases in `06-eval-cases.md`, runnable with one command | M | Evals-first |
| FR-F2 | Publishing an agent version requires passing its suite (hard gate) | M | Governance |
| FR-F3 | Scorers: programmatic asserts (action, rule IDs, tool calls) + LLM-as-judge only where unavoidable | M | Objectivity |
| FR-F4 | Failed production runs exportable as new eval cases | C | Incident→case loop |

## G. Observability & audit

| ID | Requirement | Prio | Source |
|---|---|---|---|
| FR-G1 | Per-run trace: every model call, tool call, rule applied, and decision — inspectable in UI | M | Dana's reconstructability |
| FR-G2 | Append-only audit log (no updates/deletes) | M | Priya |
| FR-G3 | Basic metrics per agent: runs, auto-approval rate, escalation rate, cost, latency | S | Ops |
| FR-G4 | Simple circuit breaker: error/cost threshold per window suspends the agent | S | Containment |

## Non-functional requirements

| ID | Requirement | Prio | Source |
|---|---|---|---|
| NFR-1 | Portability: full stack runs with `docker compose up`; cloud instance uses the same images | M | Tom |
| NFR-2 | Provider-agnostic: all model access via internal LLM gateway; provider/model per agent is configuration; centralized credentials | M | Tom |
| NFR-3 | Cost: default to economical models; routing by task; per-agent budgets enforced | M | Constraint |
| NFR-4 | Multi-tenant-ready data model (tenant_id everywhere); single active tenant | S | Honest scoping |
| NFR-5 | Segregation of duties: rule-configurator role ≠ sole approver role | S | Priya |
| NFR-6 | Latency: routine invoice decision < 60s end-to-end (demo-acceptable) | C | UX |

## Won't (this version)

SSO/enterprise auth · real ERP integrations · fine-tuning · multi-vertical · HA/scaling beyond one node · mobile UI.
