# ADR-005: LLM access = internal adapter layer ("LLM gateway")

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Agents consume LLMs with different models and budgets per agent (NFR-2, NFR-3).
Direct SDK calls scattered through the runtime would couple the platform to one
provider, spread credentials, and make cost enforcement unenforceable. How is model
access structured?

## Decision Drivers

- Provider-agnostic requirement from the IT stakeholder (NFR-2): swapping providers
  must be configuration, not surgery.
- Cost governance: per-run and per-day budgets from the DNA must be enforced at one
  choke point, with usage metered centrally.
- Credential hygiene: API keys exist only in gateway configuration, never in agent
  definitions, tool code, or the frontend.

## Considered Options

- Internal adapter layer with one contract and provider adapters behind it
- Direct provider SDK usage in the runtime
- Third-party proxy (LiteLLM or similar)

## Decision Outcome

Chosen option: **internal adapter layer**. One internal contract —
`complete(messages, tools, schema, budget) -> result` — with provider adapters
behind it (Anthropic first). Model and parameters come from each agent's DNA;
the gateway resolves them, enforces token/cost budgets before and after each call,
meters usage into the trace, and holds the only copy of API keys.

A third-party proxy would give multi-provider support for free, but hides the
budget-enforcement and tracing logic that Forge exists to demonstrate, and adds a
dependency where a thin internal layer (~one module) suffices.

### Consequences

- Good: provider swap = new adapter + config + regression evals — the eval suite
  (FR-F1) doubles as the migration safety net; every model call is budget-checked
  and traced by construction.
- Bad: we maintain adapter code per provider; each new provider means mapping its
  tool-calling and structured-output dialects onto the internal contract.
- Bad: the internal contract is the lowest common denominator — provider-specific
  features (e.g., native caching controls) need deliberate contract extensions.
