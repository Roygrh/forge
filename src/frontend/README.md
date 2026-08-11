# Forge frontend

React 18 · Vite · TypeScript (strict) · Tailwind ([ADR-007](../../docs/adr/007-frontend-react-vite.md))

**Scope:** four screens — the agent catalog, the **approval queue**, the run trace
viewer, and the **eval suite with its publish gate**. Phase 4.1 filled the first with
the real accounts-payable agents; Phase 4.4 added the queue, where a person releases or
refuses an action a run has parked, with the evidence to decide it on the same screen;
Phase 4.5 adds the Evals screen, where a version is scored against the 20 cases and the
publish action is disabled — with its reason — until the gate is met. Full agent
authoring and the knowledge screens are still deliberately absent — there is nothing
behind them yet, and a screen that cannot enforce what it displays is worse than no
screen.

## Run it

The SPA is useless without the API, so start the backend first
([`src/backend/README.md`](../backend/README.md)):

```bash
cd deploy && docker compose up -d --build      # Postgres + API + this SPA
docker compose exec api alembic upgrade head   # schema
docker compose exec api python -m scripts.seed # tenant + rules + agents
```

Then open <http://localhost:5173>. That is all — the `web` service in the compose file
runs this app.

Press **Run** on the Invoice Validator to watch a real invoice reach a rule-cited
decision. Each agent's button sends the input that shows what its definition permits: the
validator auto-approves `inv-0001` (E-01) citing R-001 and R-010; intake normalises the
same invoice and can do nothing else; comms drafts a vendor question and stops in
`awaiting_approval`, because its one tool is granted only with a human in the loop.

Then press **Run** on *Invoice Validator (approval revoked)* — the same agent with one
line of its definition changed. The run opens with a red **⛔ BLOCKED BY THE PLATFORM**
banner naming `permission_denied`, the timeline shows the denied tool call and the
governance step that stopped the run, and the explanation is written for someone who has
never seen the API. A blocked run is meant to be unmistakable from across the room; that
is the point of the whole screen.

Then open **Approvals**. The comms run is waiting there: what it wants to send, to
whom, on which invoice, the rules that were in play, and everything it looked at first —
so the decision needs no second tab (FR-E1). Approve it and the run resumes, sends the
message, and reaches its own outcome; reject it and the run is canceled with nothing sent.
Do neither and the deadline decides: an approval that runs out of time **cancels** its
run, and there is no button anywhere on this screen to extend one, because there is no
such operation in the API (FR-E3).

To watch segregation of duties bite, switch **Acting as** in the header to *Configurator*
and try to approve. The server answers 403 and names the permission that was required —
this SPA keeps no copy of who may decide what, and the refusal is recorded in the audit
log either way (NFR-5).

Running the validator on the *same* invoice twice escalates the second time: the
simulated ERP has already approved it and will not approve it again. That is deliberate —
duplicate payments are what Meridian is trying to stop — and the trace says so in words.
`docker compose restart api` rewinds the simulated ERP.

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
- **`X-Forge-Role` on every request**, initially from `VITE_FORGE_ROLE` (default
  `configurator`) and switchable from the page header. This is the demonstration of
  segregation of duties (NFR-5), not authentication: the header names an actor, the API
  records it on every event, and no credential is involved. Switching sends a different
  role name and grants nothing — the **server** decides what a role may do and answers
  403 when it may not, which is why the approval buttons are never disabled by role here.
  An unrecognised env value falls back to `configurator` rather than being forwarded, so
  a typo in an env var does not read as a broken backend.
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
| `GET /approvals` · `POST /approvals/{id}/approve` · `POST /approvals/{id}/reject` | The queue, and the two decisions there are |
| `GET /approvals/report` | The autonomy-promotion report, read-only (FR-E5) |
| `GET /eval/suites` · `POST /eval/suites/{id}/run` · `GET /eval/runs?agent_version_id=` | Evals: the suite, running it, and the gate's state per version |
| `POST /agents/{id}/versions/{v}/publish` | The publish action — answered 409 by the server while the gate is unmet (FR-F2) |

## Layout

| Path | Purpose |
|---|---|
| `src/api/types.ts` | The API shapes, mirrored from `openapi.yaml` and `app/api/schemas.py` |
| `src/api/client.ts` | The single path to the API: base URL, role header, typed errors |
| `src/App.tsx` | Four routes over `window.location.hash`: `#/`, `#/approvals`, `#/evals`, `#/runs/<id>` |
| `src/screens/AgentsScreen.tsx` | The catalog: each agent's model, tool grants, guardrails, and a Run button |
| `src/screens/RunScreen.tsx` | One run: outcome header, timeline, raw events |
| `src/screens/ApprovalsScreen.tsx` | The queue: proposed action, rules in play, evidence, Approve/Reject, and the read-only promotion report |
| `src/screens/EvalsScreen.tsx` | The suite, per-case expected-vs-actual with every assert, and the publish action with the gate's state said in words |
| `src/components/Timeline.tsx` | The ordered steps — reason, tool, decision, the platform’s own **blocked** step, and a person’s **approval** — each rendered for what it is |
| `src/components/RawEvents.tsx` | The append-only log the timeline was projected from (ADR-008) |
| `src/components/Pill.tsx` | The badge vocabulary: one colour per state, exhaustive over the contract's unions |
| `src/components/{Shell,Json,Disclosure,Feedback}.tsx` | Chrome, JSON blocks, disclosures, loading/error/empty |
| `src/lib/{format,useAsync,useActingRole}.ts` | Presentation helpers, a three-state loader, and the acting role as React state |

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
- **The badge vocabulary is exhaustive over the contract's unions — and safe beyond
  them.** `Pill.tsx` maps every run status, tool status, autonomy level and decision
  action with `Record<Union, Tone>`, so adding a state to the backend breaks the build
  here instead of rendering it grey. At runtime the lookups go through `toneFor` /
  `meaningFor`, so a value served by a newer backend than this build still renders as
  itself on a neutral badge — an unmapped state must never blank audit material.
- **Types are hand-written, for now.** ADR-007 calls for generating them from the OpenAPI
  document in CI. The consumed surface is five shapes; a generator in the build is a thing
  to maintain before there is anything to keep in sync. `src/api/types.ts` cites the
  backend module each shape mirrors.
- **The approval screen is laid out from Kevin's sentence.** *"Show me: what it wants to
  do, the invoice, the PO next to it, which rule fired, and what's off. If I have to open
  the ERP in another tab, that's two more minutes each."* So: the proposed action first,
  with its arguments as labelled fields rather than JSON to decode; the rules in play
  underneath; then everything the agent actually retrieved, inline. The evidence arrives
  with the queue, not behind a second request, because a round trip per invoice is the
  thing the requirement rules out.
- **The countdown says what happens when it runs out.** "Expires" could mean anything;
  this one cancels the run. The number comes from the server's own `seconds_remaining` —
  this screen never decides whether an approval is still live, because the browser's clock
  is not the one the deadline is measured against.
- **There is no Extend button, and no code path that would need one.** `client.ts` has no
  such call because the API has no such operation. The absence is the control.
- **The UI keeps no copy of the permission matrix.** A role that may not decide gets a 403
  naming the permission it lacked, and that is what the screen renders. Mirroring
  `ROLE_PERMISSIONS` here would be a second definition of governance, free to drift from
  the one that is enforced.
- **No router, no state library, no component library.** Three routes over the URL hash,
  one `useAsync` hook, one `useSyncExternalStore` for the acting role, and Tailwind. Each of those would be a dependency carried for a screen
  that does not need it.
- **The compose image runs the dev server, on purpose.** Vite inlines `VITE_*` at build
  time, so a static production image would have to be rebuilt for every environment it is
  pointed at. The dev server reads the value at start-up, which keeps `docker compose up`
  one command that works on any host. `npm run build` is what a real deployment ships;
  swapping the Dockerfile's final stage for nginx is the change to make when there is a
  real environment to ship to.
