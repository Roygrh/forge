# Data Model

One PostgreSQL 16 store holds everything ([ADR-004](../adr/004-postgres-single-store.md)):
relational tables for platform state, an **append-only `events` table** for audit and
trace ([ADR-008](../adr/008-append-only-audit.md)), and `pgvector` for knowledge
embeddings. Every business table carries `tenant_id` (NFR-4), so the schema is
multi-tenant-ready while a single tenant is active. Agent DNA lives as validated `jsonb`
— the contract is stored whole, never shredded.

```mermaid
erDiagram
    tenants ||--o{ agents : owns
    tenants ||--o{ knowledge_collections : owns
    tenants ||--o{ eval_suites : owns
    agents ||--o{ agent_versions : versions
    agent_versions ||--o{ runs : executes
    agent_versions ||--o{ eval_runs : "gated by"
    runs ||--o{ run_steps : contains
    run_steps ||--o{ tool_invocations : issues
    tool_invocations ||--o| approvals : "may require"
    knowledge_collections ||--o{ knowledge_chunks : contains
    eval_suites ||--o{ eval_cases : contains
    eval_suites ||--o{ eval_runs : "evaluated by"
    runs ||--o{ events : records

    tenants {
        uuid tenant_id PK
        text slug
        text name
        timestamptz created_at
    }
    agents {
        uuid id PK
        uuid tenant_id FK
        text slug "unique per tenant"
        text name
        text type "chatbot | workflow | autonomous"
        text description
        timestamptz created_at
    }
    agent_versions {
        uuid id PK
        uuid tenant_id FK
        uuid agent_id FK
        text version "semver"
        jsonb dna "validated vs dna-schema.json at write"
        text status "draft | published | suspended"
        uuid published_eval_run_id FK "gate evidence, nullable"
        timestamptz published_at
        timestamptz created_at
    }
    runs {
        uuid id PK
        uuid tenant_id FK
        uuid agent_version_id FK
        text status "running | awaiting_approval | completed | escalated | canceled | error"
        text trigger
        int total_tokens
        numeric total_cost_usd
        timestamptz started_at
        timestamptz finished_at
    }
    run_steps {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        int step_no
        text kind "reason | tool | decision"
        jsonb model_call "model, tokens, cost"
        jsonb decision "action plus rule citations"
        timestamptz created_at
    }
    tool_invocations {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid run_step_id FK
        text tool_ref "slug at semver"
        text autonomy "autonomous | requires_approval | forbidden"
        jsonb args
        jsonb result
        text status "validated | executed | blocked | denied"
        timestamptz created_at
    }
    approvals {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid tool_invocation_id FK
        text status "pending | granted | rejected | expired"
        timestamptz expires_at "server-side, fail-closed"
        text decision "approve | reject, null until decided"
        text decided_by "actor"
        timestamptz decided_at
        text note
        timestamptz created_at
    }
    knowledge_collections {
        uuid id PK
        uuid tenant_id FK
        text slug
        text name
        text authority_level "sme_validated | policy_2023 | policy_2019"
        text owner
        timestamptz created_at
    }
    knowledge_chunks {
        uuid id PK
        uuid tenant_id FK
        uuid collection_id FK
        text source_ref "document or rule id"
        text section
        text rule_id "R-xxx, nullable"
        text authority_level "denormalized for ranking"
        text content
        vector embedding "pgvector, semantic"
        tsvector lexical_tsv "full-text, lexical"
        timestamptz created_at
    }
    eval_suites {
        uuid id PK
        uuid tenant_id FK
        text slug
        text name
        text version "semver"
        timestamptz created_at
    }
    eval_cases {
        uuid id PK
        uuid tenant_id FK
        uuid suite_id FK
        text code "E-xx"
        text scenario
        text expected_action
        jsonb expected_citations "R-xxx list"
        jsonb must_not_call "e.g. approve_invoice"
    }
    eval_runs {
        uuid id PK
        uuid tenant_id FK
        uuid suite_id FK
        uuid agent_version_id FK
        text status "running | completed"
        bool passed "publish-gate result"
        int total
        int passed_count
        jsonb case_results "per-case pass/fail detail"
        timestamptz created_at
    }
    events {
        bigint event_id PK "monotonic"
        uuid tenant_id FK
        timestamptz occurred_at
        text type "run.started, decision.made, approval.granted, version.published, ..."
        text actor "system or user id"
        uuid run_id FK "soft ref, nullable"
        uuid agent_version_id FK "soft ref, nullable"
        uuid approval_id FK "soft ref, nullable"
        jsonb payload "typed by event type"
    }
```

## Notes

**Key relationships.** An `agent` is an identity; its behaviour is a series of immutable
`agent_versions`. A `run` is bound to the exact `agent_version` that produced it (FR-A3),
so any historical decision is reproducible against the DNA that made it. `run_steps`
decompose a run into reason/tool/decision steps; `tool_invocations` hang off the step
that issued them and, when the tool's autonomy is `requires_approval`, own exactly one
`approval` (FR-E2). Knowledge is `collections → chunks`; evals are `suites → cases`, with
each `eval_run` scored against one `agent_version`.

**Events are the source of truth.** The `events` table is append-only: the application
role is granted `INSERT`/`SELECT` only — no `UPDATE`, no `DELETE` (ADR-008). Immutability
is a database grant, not a convention. Every state transition and decision is written as
an event in the same transaction as the state-row change, so run state, the approval
queue, and lifecycle history are all **reconstructable from events** (FR-G1, FR-G2). The
soft references (`run_id`, `agent_version_id`, `approval_id`) are nullable because a
single event type only populates the refs it concerns; the relational tables are the
fast read path, events are the audit ground truth.

**Why DNA as `jsonb`, not shredded columns.** The golden rule is that the DNA JSON Schema
is *the* contract and nothing bypasses it. Storing the whole validated document as one
`jsonb` value keeps the database faithful to that contract: the schema — versioned in
[`dna-schema.json`](./dna-schema.json) — is the single authority on structure, validated
at write time before the row is accepted. Shredding DNA into columns would fork the
contract into a second, drifting definition and would couple every schema evolution to a
migration. `jsonb` also lets us index into the document (e.g. `dna->'model'->>'provider'`)
without pretending the relational schema owns the shape. The tradeoff is that structural
guarantees come from application-side validation plus a `CHECK`, not from column types —
acceptable because the schema is the deliberate single source of structure.

**Knowledge: authority + hybrid search.** Each `knowledge_chunk` carries an
`authority_level` (denormalized from its collection so ranking is a local read) plus both
an `embedding` (pgvector, semantic) and a `lexical_tsv` (Postgres full-text, lexical).
Retrieval combines the two — exact terms like vendor names and invoice numbers must hit
(FR-D3) — and the authority hierarchy (`sme_validated` > `policy_2023` > `policy_2019`)
orders conflicting sources so they are surfaced, never averaged (FR-D2). `rule_id` lets a
chunk be cited by ID (R-xxx) to satisfy `require_citations` (R-092, FR-D4).

## Open questions

- **Per-case eval results as `jsonb` vs a dedicated table.** `eval_runs.case_results`
  holds per-case pass/fail inline. This is enough for the publish gate (a single `passed`
  boolean) but is not relationally queryable — which matters if FR-F4 ("failed production
  runs exportable as new eval cases") grows into per-case trend analytics. Splitting an
  `eval_case_results` table is deferred until that read pattern is real, not invented now.
