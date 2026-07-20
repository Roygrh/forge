# ADR-004: Persistence = PostgreSQL 16 as the single store

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Forge needs relational state (agents, versions, runs, approvals), an append-only
event/audit log (FR-G2), and vector search for knowledge retrieval (FR-D3). Should
these be separate specialized stores or one database?

## Decision Drivers

- Operational simplicity: single builder, `docker compose up` must bring up the
  full stack (NFR-1); every extra store is another container, backup, and failure mode.
- Transactional integrity: a run's state transition and its audit event must commit
  atomically — trivial in one database, distributed-consistency work across two.
- Scale honesty: ~1,400 invoices/month and a handful of policy documents is far
  below the threshold where specialized stores pay for themselves.

## Considered Options

- PostgreSQL 16 alone (relational + append-only events + pgvector)
- PostgreSQL + Redis (queues/cache) + dedicated vector DB (Qdrant/Weaviate)

## Decision Outcome

Chosen option: **PostgreSQL 16 as the single store**. Relational tables for platform
state, an append-only events table for audit, pgvector for embeddings, and Postgres
full-text search combined with vector similarity for hybrid retrieval. Fewer moving
parts wins at this scale, and one ACID boundary keeps state + audit atomically
consistent.

**Revisit thresholds** (documented so the tradeoff is honest, not ignored):
- Vector corpus > ~1M embeddings or recall/latency SLOs pgvector can't meet →
  dedicated vector DB.
- Sustained queue throughput or pub/sub fan-out beyond LISTEN/NOTIFY comfort
  (~hundreds of events/sec) → Redis or a broker.
- Event table growth requiring independent retention/archival → dedicated event store.

### Consequences

- Good: one backup, one connection pool, one migration tool; atomic state+audit
  writes; the demo stack is two app containers and one database.
- Bad: pgvector's index tuning (HNSW/IVFFlat) is less turnkey than managed vector
  DBs; hybrid ranking is hand-assembled SQL.
- Bad: the events table serves both audit and read-model duties — acceptable now,
  but a known coupling if read patterns diverge (see ADR-008).
