# ADR-009: Deployment = Docker Compose reference deployment

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Forge must run identically for three audiences: the builder's machine, an evaluator
cloning the repo, and a low-cost public demo instance. The IT stakeholder's story is
on-premise deployability (NFR-1): "runs inside our walls with `docker compose up`".

## Decision Drivers

- Portability as a stakeholder requirement, not an aspiration: one command, full stack.
- Free/near-free infrastructure constraint; single node is explicitly in scope,
  HA explicitly out (charter §3).
- One artifact set: the images an evaluator runs locally must be byte-identical to
  the ones serving the public instance — no environment-specific builds.

## Considered Options

- Docker Compose as the reference deployment; same images reused for cloud
- Kubernetes (k3s/managed)
- PaaS-native deploys (Fly.io/Render buildpacks) without a compose story

## Decision Outcome

Chosen option: **Docker Compose as the reference deployment**. Three services —
backend, frontend (static files behind a lightweight server), PostgreSQL 16 with
pgvector — plus seed data. The compose file *is* the on-premise story. A future
cloud instance runs the **same images** with different environment configuration
(secrets, hostnames), keeping dev/prod parity by construction.

Kubernetes would demonstrate ops fluency but is dishonest at one node — it adds
operational surface the project explicitly scoped out, and the evaluators' 15-minute
walkthrough should not include cluster setup. PaaS-only deploys invert the priority:
the on-premise narrative is the differentiator, the public instance is a convenience.

### Consequences

- Good: `docker compose up` is the entire install; evaluator, builder, and demo
  environments cannot drift; images are the single deployment artifact.
- Bad: no orchestration features — restart policies stand in for health-managed
  rollouts; scaling story is "buy a bigger node", which matches scope but must be
  said out loud.
- Bad: secrets management is env-file grade, acceptable for a demo, flagged as the
  first hardening item for any real deployment.

## Amendment — Phase 5.1 (2026-08-21)

The decision above stands; three things about *how* it is realised changed once the
stack was measured against its actual audience — someone who clones the repository and
runs it once. Nothing here alters the choice of Compose, the service topology, or the
one-artifact-set constraint.

**1. `docker compose up` now migrates and seeds itself.** The original build made
`alembic upgrade head` and `python -m scripts.seed` manual follow-up commands, on the
principle that migrations must never be implicit on boot. That principle survives; the
manual typing does not. A one-shot **`migrate` service** runs both (`python -m
scripts.init_db`) and the `api` service depends on its `service_completed_successfully`.

The alternative was an entrypoint on the API container that migrates before starting
uvicorn. It was rejected: an entrypoint puts migration inside the process that serves
traffic, so it races itself the moment there is more than one replica, its output is
tangled with request logs, and a migration failure becomes a crash-looping API rather
than a stopped deployment. The one-shot container keeps the property the Dockerfile
always claimed — the API never migrates the database it is about to serve — while
removing the step a person had to remember. It costs one more container in `docker
compose ps -a`, which is a fair price for a step that is visible, separately logged, and
gated on.

`db` is gated by a healthcheck that connects over **TCP** (`pg_isready -h 127.0.0.1`).
The default socket check passes during the official image's `initdb` phase, when a
temporary server is listening on the unix socket only — a genuine race that a "wait for
healthy" would not have caught. `init_db.py` additionally retries a real `SELECT 1`, so
readiness of the database is established by connecting to it rather than by asking
about it.

**2. The frontend ships as a production build.** The image ran Vite's dev server because
Vite inlines `VITE_*` at build time, so a static build would have had the API's address
baked in and the image would have been environment-specific — which contradicts the
"same images everywhere" driver above. Serving the config *at container start* resolves
that: nginx's own entrypoint expands `${FORGE_*}` into a one-line `/config.js` the page
loads before its bundle, and `src/api/client.ts` falls back to `VITE_*` and then to a
documented default. So the production build and the parity claim are no longer in
tension, and the claim is now true rather than aspirational: `forge-web:local` is
repointed with an environment variable, not a rebuild.

**3. Health split into liveness and readiness.** One route reporting both process and
database state is the wrong shape for any hosting platform: gate a liveness probe on the
database and an outage restarts the API, which fixes nothing. `GET /health` is now
dependency-free; `GET /ready` answers 503 until the database responds, the schema is at
this build's Alembic head, and something is published to run. Compose gates the `api`
service's health on `/ready`, which is what makes "the stack is up" an observation
rather than a guess.

### Consequences of the amendment

- Good: a cold start is one command with no follow-up, and its readiness is
  machine-checkable.
- Good: the frontend image is genuinely environment-independent, so the parity driver is
  satisfied by construction rather than by intention.
- Bad: `/config.js` is one extra request before the SPA boots, and the SPA now has two
  configuration sources (runtime and build-time) to keep straight. The fallback order is
  stated once, in `client.ts`.
- Bad: the backend image is now named (`forge-backend:local`) so two services can share
  one build. Two services declaring the same build **and** the same tag makes two
  builders race to export it and fails the `up`, so only `api` builds and `migrate`
  names the result — a coupling that is invisible until it breaks, and is commented in
  the compose file where it lives.
