# CLAUDE.md — Forge

Forge is a governed agent factory: business agents are declarative JSON artifacts
("DNA") executed by one runtime, with governance embedded structurally — least-privilege
tools, HITL approvals, eval-gated publishing, full traceability. Demonstrated end-to-end
with accounts-payable automation for a simulated client (Meridian Supply Co.).

## Frozen tech stack (see docs/adr/ for rationale)

| Layer | Choice | ADR |
|---|---|---|
| Backend | Python 3.12 + FastAPI + Pydantic v2 | ADR-002 |
| Agent runtime | Custom lightweight loop (no LangGraph/CrewAI) | ADR-003 |
| Persistence | PostgreSQL 16 (relational + append-only events + pgvector) | ADR-004 |
| LLM access | Internal adapter layer ("LLM gateway"), Anthropic first | ADR-005 |
| Model I/O | Structured outputs validated against JSON Schema | ADR-006 |
| Frontend | React 18 + Vite + TypeScript + Tailwind (SPA) | ADR-007 |
| Audit | Append-only events table, no UPDATE/DELETE grants | ADR-008 |
| Deployment | Docker Compose reference deployment; same images for cloud | ADR-009 |

## Repo layout (ADR-001)

```
docs/                  Source of truth: charter, discovery, architecture, ADRs
  01-discovery/        Client profile, tacit rules (R-xxx), requirements, eval cases
  02-architecture/     DNA schema + examples, C4 model, contracts
  adr/                 Architecture decision records (MADR)
src/backend/           Python 3.12 FastAPI service (runtime, gateways, API)
src/frontend/          React 18 + Vite + TypeScript SPA
deploy/                Docker Compose, images, seed data
```

## Coding conventions

- **Python**: 3.12, full type hints (mypy-clean), `ruff` for lint + format, `pytest`
  for tests. Pydantic v2 models at every boundary. Async-first in FastAPI handlers.
- **TypeScript**: `strict: true`, no `any` without a comment justifying it.
- Tests live next to the layer they test; eval cases live in `docs/01-discovery/06-eval-cases.md`
  and are the publish gate — never weaken a case to make it pass.

## Golden rules

1. **The agent DNA JSON Schema is the central contract; nothing bypasses it.**
   The runtime executes only what a valid, versioned definition declares.
2. **All tool calls go through the tool gateway. All model calls go through the
   LLM adapter layer. No exceptions — not in tests, not in demos.**
3. **Fail closed.** On doubt, ambiguity, or missing permission → escalate.
   Never guess, never execute. Expiring approvals cancel; they never auto-approve.
4. **Every decision an agent makes must cite rule IDs (R-xxx) and be traced.**
   A decision without citations is a bug, not a style issue.
5. **docs/ is source of truth.** If code and docs diverge, fix one explicitly —
   never let them drift silently.
