# ADR-007: Frontend = React 18 + Vite + TypeScript + Tailwind

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

The UI must let a non-technical operator create/edit agents in a catalog (FR-A2),
work an approval queue with evidence side-by-side (FR-E1), and inspect per-run
traces (FR-G1). It is an internal operations SPA behind a login — no SEO, no
content pages, no SSR needs.

## Decision Drivers

- Fastest credible path for three data-dense screens: catalog, approval queue,
  trace viewer.
- Type safety end-to-end: TypeScript strict mode, with API types generated from
  the FastAPI OpenAPI spec.
- Single builder: mainstream ecosystem, minimal build/config surface.

## Considered Options

- React 18 + Vite + TypeScript + Tailwind (SPA)
- Next.js (SSR/RSC)
- Server-rendered templates from FastAPI (Jinja + HTMX)

## Decision Outcome

Chosen option: **React 18 + Vite + TypeScript (strict) + Tailwind**, as a SPA
talking to the FastAPI backend. Next.js adds a server runtime, routing conventions,
and RSC mental overhead that buy nothing for an authenticated internal tool.
Server-rendered templates would be lighter still, but the approval queue and trace
viewer are interaction-heavy (live queue state, expandable trace steps, JSON
editing) where a component model earns its keep.

### Consequences

- Good: instant dev feedback via Vite; Tailwind keeps styling fast without design
  overhead; the SPA is static files — trivially served from a container (ADR-009).
- Bad: client-side rendering means the API must carry all state; initial load ships
  the full bundle — irrelevant at this user count, noted for honesty.
- Bad: React 18 + strict TS discipline requires generated API types to stay in sync
  with the backend; enforced by regenerating types in CI from the OpenAPI spec.
