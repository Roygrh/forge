# Agent DNA — the central contract

## What it is

An agent in Forge is not code. It is one JSON document — its **DNA** — valid against
[`dna-schema.json`](./dna-schema.json) (JSON Schema draft 2020-12). The DNA declares
everything the agent is and may do: identity and version, instructions, tool grants
with autonomy levels, knowledge collections, model and budgets, guardrails, and its
evaluation suite. See [`dna-examples/invoice-validator.agent.json`](./dna-examples/invoice-validator.agent.json)
for a complete example.

## Contract philosophy

**The runtime only executes what's declared.** A single runtime interprets any valid
DNA; there is no per-agent code path. Consequences, by construction:

- A tool absent from `tools` does not exist for the agent — least privilege is the
  shape of the document, not a runtime check that could be skipped.
- Every tool call passes the gateway, every model call passes the LLM adapter layer;
  the DNA supplies the parameters, never the credentials.
- **Fail-closed defaults are `const` in the schema.** `escalate_on_no_rule_match`,
  `require_citations`, `publish_gate`, and `authority_policy: highest_wins` are
  required fields locked to a single value: a definition that tries to disable them
  is not a permissive agent — it is an invalid document that will not load.
  Governance is a structural property, not a configuration option.
- Nothing bypasses the schema: not the catalog UI, not the API, not tests or demos.

## Versioning and lifecycle

DNA documents are **immutable per version** (semver). Any change — one character of
the task prompt included — is a new version. Every run records the exact version
that produced it, so any historical decision is reconstructable against the
definition that made it.

Lifecycle: **draft → published → suspended → rebuilt.**

- **draft**: editable, runnable only in evaluation mode.
- **published**: the gate — a version is publishable only after passing its declared
  eval suite (`evals.suite_ref`, the 20 cases defined before implementation). The
  gate is hard: the platform has no override path, because `publish_gate` cannot
  be false.
- **suspended**: manually, or by circuit breaker; runs stop, history remains.
- **rebuilt**: a new draft version cut from any prior version; it re-enters the
  gate like any other.

References inside the DNA (`slug@semver`) pin instruction blocks, tools, knowledge
collections, and eval suites the same way — the whole dependency graph of a
published agent is frozen and auditable.

## Open questions

- Whether `versioned_ref` without an explicit version should be *forbidden* in
  published (vs draft) definitions, forcing full pinning at publish time.
- Whether tool `config` payloads should be hashed into the run record independently,
  so gateway-side config-schema evolution stays detectable.
