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
