# Forge

**A governed agent factory** — where enterprise AI agents are *configuration artifacts*, not code.

One runtime interprets many agents. Each agent is a declarative document (its "DNA"): its role, the tools it may use and at what autonomy level, the knowledge it may read, its model and budgets, and its guardrails. A business user creates a new agent by writing that document — never by writing code. Governance is not a feature bolted on top; it is a structural property of the platform: an agent can only ever do what its DNA declares, high-impact actions require human approval, every decision is traced, and nothing reaches production without passing its evaluation suite.

The platform is demonstrated end to end with one realistic vertical — **accounts-payable invoice approval** for a simulated mid-market client — because when money moves, the value of governance is obvious.

> ⚠️ **Work in progress, built in the open.** This repository is being developed design-first: the architecture and contracts are established before the code, and the history is meant to show the reasoning, not just the result.

## Why this design

The core idea — *one runtime, N agents defined declaratively* — is what lets a platform scale to many agents without the engineering team growing with each one, and what lets non-programmers create and operate agents safely. The recurring principle throughout is **fail closed**: on any doubt, missing permission, or unmatched rule, the system escalates to a human rather than guessing or acting.

## Repository tour

The `docs/` folder is the source of truth and is numbered to read in order:

- **`docs/00-charter.md`** — what Forge is, its scope, and the frozen decisions.
- **`docs/01-discovery/`** — the (simulated) client, its stakeholders, the interviews, and the captured business rules and evaluation cases. This is the requirements phase.
- **`docs/02-architecture/`** — the C4 model, the behavioral diagrams, the data model, the **agent DNA contract** (`dna-schema.json`), and the API contract (`openapi.yaml`).
- **`docs/adr/`** — the architecture decision records: each significant choice with its context, alternatives, and trade-offs.
- **`src/backend/`** — the platform itself (Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL 16 + pgvector). See its own README for how to run it.

## Status

| Phase | | State |
|---|---|---|
| 0 | Planning & charter | ✅ Complete |
| 1 | Discovery & requirements | ✅ Complete |
| 2 | Architecture & contracts | ✅ Complete |
| 3 | Walking skeleton (running platform foundation) | 🔄 In progress |
| 4 | Capabilities (agents, governance, knowledge, HITL, evals, observability) | ⬜ Planned |
| 5 | Deployment | ⬜ Planned |
| 6 | Demo packaging | ⬜ Planned |

**The walking skeleton runs end to end today.** `docker compose up` brings up PostgreSQL and the API; a seeded agent — a declarative DNA document, validated against `dna-schema.json` — is loaded by the runtime, which calls a model through the LLM gateway under the budgets its DNA declares, invokes a tool through the tool gateway after checking the autonomy its DNA grants, and reaches a decision that cites a rule ID. Every model call, tool call, decision, and refusal is appended to the audit log, and `GET /runs/{id}/trace` reconstructs the whole run from those events alone. It does this with no API key and no network: the provider is a line in the DNA, and swapping it is the only change needed to run the same agent against a real model.

The business rules, knowledge retrieval, human approvals, and the eval gate are Phase 4 — the skeleton is deliberately trivial so that what it demonstrates is the *governance path*, not the agent. See `src/backend/README.md` for the three-command quickstart and a runnable trace.
