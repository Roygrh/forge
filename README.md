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
- **`docs/demo-script.md`** — the ten-minute walkthrough, in a technical and a non-technical
  version, with pre-flight and recovery. Every beat is asserted by the test suite.
- **`docs/01-discovery/`** — the (simulated) client, its stakeholders, the interviews, and the captured business rules and evaluation cases. This is the requirements phase.
- **`docs/02-architecture/`** — the C4 model, the behavioral diagrams, the data model, the **agent DNA contract** (`dna-schema.json`), and the API contract (`openapi.yaml`).
- **`docs/adr/`** — the architecture decision records: each significant choice with its context, alternatives, and trade-offs.
- **`src/backend/`** — the platform itself (Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL 16 + pgvector). See its own README for how to run it.
- **`src/frontend/`** — the operations SPA (React 18 · Vite · TypeScript · Tailwind): the agent catalog, the approval queue, and the run trace viewer.

## Status

| Phase | | State |
|---|---|---|
| 0 | Planning & charter | ✅ Complete |
| 1 | Discovery & requirements | ✅ Complete |
| 2 | Architecture & contracts | ✅ Complete |
| 3 | Walking skeleton (running platform foundation) | ✅ Complete |
| 4.1 | The accounts-payable domain (ERP, tools, rules as data, three agents) | ✅ Complete |
| 4.2 | Governance in depth (autonomy, fail-closed, limits, SoD, visible blocks) | ✅ Complete |
| 4.3 | Knowledge (authority-ranked retrieval, conflict resolution, citations) | ✅ Complete |
| 4.4 | Human in the loop (approval queue, fail-closed expiry, autonomy report) | ✅ Complete |
| 4.5 | Evaluation suite as publish gate (20 seeded cases, offline runner, hard 409) | ✅ Complete |
| 4.6 | Observability & containment (per-agent metrics from the event log, circuit breaker, manual resume) | ✅ Complete |
| 5.1 | Deployment polish (one-command cold start, liveness/readiness, documented configuration) | ✅ Complete |
| 6.1 | Demo packaging (curated story data, 10-minute script in two versions, case picker in the UI) | ✅ Complete |

## Quickstart

You need Docker, and nothing else. No API key, no `.env` file, no follow-up commands.

```bash
git clone <this repo> && cd forge/deploy
docker compose up -d --build
```

The command builds two images and starts four containers, in an order the file enforces:
PostgreSQL comes up, a one-shot `migrate` container waits for it, applies the migrations
and seeds Meridian's rule set, eval suite and agents, and only when that container exits 0
does the API start. Then:

```bash
curl http://localhost:8000/api/v1/ready
# {"status":"ready","checks":{"database":"ok","migrations":"ok","seed":"ok"}, ...}
```

Open <http://localhost:5173> for the UI and <http://localhost:8000/api/v1/docs> for the
API. `docker compose logs migrate` shows exactly what was installed. The whole thing runs
offline: the shipped agents name a deterministic in-process provider, so there is no
credential to supply and nothing to pay for.

**Ten minutes, five beats, no hunting for an invoice id.** Each agent card carries a **Case to
run** picker holding the demo story in order — a clean approval, the same vendor over the CFO's
threshold, a duplicate that gets blocked, a message a person must release, and a policy question
three of Meridian's own sources answer differently. `docs/demo-script.md` narrates all five, twice:
once for an engineer and once for someone who will never open a terminal. The beats are defined in
one place (`app/demo_story.py`) and executed end to end by the test suite on every build, so the
script cannot quietly stop being true.

**A real invoice reaches a rule-cited decision today, in a browser.** Press **Run** on the Invoice Validator and it reads the invoice from the simulated ERP, establishes the vendor's trust tier and history, matches the purchase order and the goods receipts, retrieves the rules that apply — and decides, citing them:

```
auto_approve · cites R-001, R-010
  R-001 (vendor.trust_tier eq 'trusted'; vendor.relationship_years gte 3;
         match.po_found is_true; match.price_variance_pct lte 2 (actual 0.80))
```

Send it a $12,000 invoice instead and two rules fire with different answers, so the most restrictive wins and the decision says so: `escalate · cites R-001, R-010, R-020, R-090`. Send it a duplicate invoice number and it blocks — and `approve_invoice` is never called. Every model call, tool call, decision, and refusal is appended to the audit log, and `GET /runs/{id}/trace` reconstructs the whole run from those events alone. It does this with no API key and no network: the provider is a line in the DNA, and swapping it is the only change needed to run the same agent against a real model.

**The rules are data, not code.** Meridian's tacit rules (R-001 … R-092) are rows in a table, each with its statement, its authority, and machine-evaluable conditions. The validator agent contains none of them — it retrieves them and reasons over what it retrieved. Lower a threshold with one `UPDATE` and the next run decides differently: no code change, no rebuild, no redeploy.

**Least privilege is visible on the screen.** The agents differ only in what their definitions grant: intake may read an invoice and nothing else; the validator may approve one up to a ceiling declared in its DNA, and is *forbidden* to schedule payments; comms may not contact a vendor without a human, so its run stops in `awaiting_approval` with the message drafted and unsent. Each of those is enforced at the tool gateway and recorded in the trace.

**And when the platform stops something, it says so.** Every refusal — a tool the definition forbids, a blown budget, a step limit, a decision below its confidence floor, a case no rule covers — carries a machine-readable reason code, a plain-language explanation, and its own step in the trace. Press **Run** on *Invoice Validator (approval revoked)*, which is the validator with one line of its definition changed, and the run opens with:

```
⛔ BLOCKED BY THE PLATFORM     permission_denied

The agent asked for a tool its own definition does not permit it to use.
Least privilege is part of the published definition, so the call was
refused and nothing was executed.
```

A tool handler is invoked in exactly one place in the codebase, and a test reads the source tree to keep it that way. No role may both configure an agent and approve its actions — that is a permission matrix the build refuses to start without, not a note in a policy document.

**Nothing ships without passing its evals.** The 20 evaluation cases written during discovery — before the agents existed — are seeded into the database and runnable with one command (`python -m scripts.run_evals`): each case executes a real run of the version under test, deterministic and offline, and is scored by programmatic asserts — final action, cited rule IDs, tools called and *not* called, budgets, and a reconstructable trace. `POST .../publish` is the gate itself: it answers **409** until this exact version has a completed, passing eval run for the suite its own DNA declares, and the passing run is recorded on the version as the publish's evidence. `python -m scripts.demo_publish_gate` prints the whole story — refused with 409, 20/20 green, published with the eval run attached. The **Evals** screen shows every case's expected-vs-actual and disables the publish action with its reason while the gate is unmet — but the button is a courtesy; the 409 is the control.

**And it starts from nothing, first try.** `docker compose down -v && docker compose up -d --build` leaves a migrated, seeded, working system with no manual step — the migration and the seed are a one-shot container the API waits on, the database gate is a real TCP healthcheck rather than a guess, and `GET /api/v1/ready` distinguishes "still starting" from "broken" by naming the check that failed. Every variable the system reads is listed with its default in a committed `.env.example`; none of them is required, and no secret is committed anywhere.

See `src/backend/README.md` for the API, the configuration reference and the test suite, and `src/frontend/README.md` for the UI.
