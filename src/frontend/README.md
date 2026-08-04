# Forge frontend

React 18 · Vite · TypeScript (strict) · Tailwind ([ADR-007](../../docs/adr/007-frontend-react-vite.md))

**Phase 3.3 scope:** the two screens that close the walking skeleton — the agent catalog,
and the run trace viewer. Agent authoring, the approval queue, knowledge and eval screens
are Phase 4 and are deliberately absent: there is nothing behind them yet, and a screen
that cannot enforce what it displays is worse than no screen.

## Run it

The SPA is useless without the API, so start the backend first
([`src/backend/README.md`](../backend/README.md)):

```bash
cd deploy && docker compose up -d --build      # Postgres + API + this SPA
docker compose exec api alembic upgrade head   # schema
docker compose exec api python -m scripts.seed # tenant + skeleton agent
```

Then open <http://localhost:5173>. That is all — the `web` service in the compose file
runs this app.

To work on the SPA itself, run it from source against the same API:

```bash
cd src/frontend
npm install
npm run dev        # http://localhost:5173, hot reload
```

Both paths use port 5173, so stop the compose `web` service (`docker compose stop web`)
before running the dev server locally.

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server with hot reload |
| `npm run build` | Type-check (`tsc --noEmit`), then build to `dist/` |
| `npm run typecheck` | Types only |
| `npm run preview` | Serve the built `dist/` |

## How it talks to the backend

Every call goes through one wrapper, [`src/api/client.ts`](./src/api/client.ts) — which
is what makes the following true by construction rather than by discipline.

- **One base URL**, from `VITE_API_BASE_URL` (default `http://localhost:8000`), with
  `/api/v1` appended. Copy [`.env.example`](./.env.example) to `.env` to point the SPA
  at another backend.
  Vite inlines `VITE_*` at build time and injects them at dev-server start, so this
  value is always **the address the browser can reach** — never a Docker service name
  like `http://api:8000`, which resolves to nothing on the user's machine.
- **`X-Forge-Role` on every request**, from `VITE_FORGE_ROLE` (default `configurator`).
  This is the demonstration of segregation of duties (NFR-5), not authentication: the
  header names an actor, the API records it on every event, and no credential is
  involved. It is shown in the page header for exactly that reason. An unrecognised
  value falls back to `configurator` rather than being forwarded, so a typo in an env
  var does not read as a broken backend.
- **Failures arrive as `ApiError`**, carrying the platform's `{code, message, details}`
  body, and are rendered with their code visible. "The screen shows exactly what
  happened" does not stop being true when something goes wrong.

The API is on a different origin, so the browser preflights every call. The backend
allows this origin explicitly — see `CORS_ORIGINS` in `deploy/docker-compose.yml` and
its default in `src/backend/app/config.py`. Ports other than 5173 need adding there.

Endpoints consumed, all read-only except the one that starts a run:

| Call | Screen |
|---|---|
| `GET /agents` · `GET /agents/{id}/versions` | Catalog: what exists, and its DNA |
| `POST /runs` | The Run button |
| `GET /runs/{id}` · `GET /runs/{id}/trace` | Run view: header, timeline, raw events |

## Layout

| Path | Purpose |
|---|---|
| `src/api/types.ts` | The API shapes, mirrored from `openapi.yaml` and `app/api/schemas.py` |
| `src/api/client.ts` | The single path to the API: base URL, role header, typed errors |
| `src/App.tsx` | Two routes over `window.location.hash`: `#/` and `#/runs/<id>` |
| `src/screens/AgentsScreen.tsx` | The catalog: each agent's model, tool grants, guardrails, and a Run button |
| `src/screens/RunScreen.tsx` | One run: outcome header, timeline, raw events |
| `src/components/Timeline.tsx` | The ordered steps — reason, tool, decision — each rendered for what it is |
| `src/components/RawEvents.tsx` | The append-only log the timeline was projected from (ADR-008) |
| `src/components/Pill.tsx` | The badge vocabulary: one colour per state, exhaustive over the contract's unions |
| `src/components/{Shell,Json,Disclosure,Feedback}.tsx` | Chrome, JSON blocks, disclosures, loading/error/empty |
| `src/lib/{format,useAsync}.ts` | Presentation helpers, and a three-state loader |

## Notes for reviewers

- **The run view is an argument, in three layers.** The header is the outcome; the
  timeline is the projection a reviewer reads; the raw-events panel underneath is the
  append-only log that projection came from. The API serves both halves, so the screen
  can be *checked* rather than trusted ([ADR-008](../../docs/adr/008-append-only-audit.md)).
  The panel states the arithmetic — six events appended, four of them steps — because the
  two lifecycle events (`run.started`, `run.completed`) are real, appended, and correctly
  absent from the timeline.
- **The gateway's verdict is stated in words, before any payload.** A tool step leads
  with the tool ref, the autonomy its DNA grants, and a sentence saying what the gateway
  did — including for a call it refused. Refusals are recorded precisely so they can be
  seen (FR-C5), so the UI shows them as first-class, not as a missing result.
- **Citations get their own block.** A decision without cited rule IDs is a bug, not a
  style issue (golden rule 4), and `require_citations` is const-locked true in the DNA
  schema. Rendering them as small print would misstate what they are.
- **The catalog reads DNA, not a summary of it.** Model, tool grants with autonomy, and
  guardrails all come from the version's own DNA document — the same one the runtime
  executes — so a card cannot describe an agent that differs from the one that will run.
  A version published without eval-gate evidence says so on its card.
- **Money is never parsed.** `total_cost_usd` and per-step `cost_usd` arrive as exact
  decimal strings and are prefixed with `$`, never passed through `Number()`. Rounding an
  audit figure through a float is the thing the backend went out of its way to avoid.
- **The badge vocabulary is exhaustive over the contract's unions.** `Pill.tsx` maps every
  run status, tool status, autonomy level and decision action with `Record<Union, Tone>`,
  so adding a state to the backend breaks the build here instead of rendering it grey.
- **Types are hand-written, for now.** ADR-007 calls for generating them from the OpenAPI
  document in CI. The consumed surface is five shapes; a generator in the build is a thing
  to maintain before there is anything to keep in sync. `src/api/types.ts` cites the
  backend module each shape mirrors.
- **No router, no state library, no component library.** Two routes over the URL hash, one
  `useAsync` hook, and Tailwind. Each of those would be a dependency carried for a screen
  that does not need it.
- **The compose image runs the dev server, on purpose.** Vite inlines `VITE_*` at build
  time, so a static production image would have to be rebuilt for every environment it is
  pointed at. The dev server reads the value at start-up, which keeps `docker compose up`
  one command that works on any host. `npm run build` is what a real deployment ships;
  swapping the Dockerfile's final stage for nginx is the change to make when there is a
  real environment to ship to.
