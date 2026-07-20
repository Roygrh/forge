# ADR-006: Model responses = structured outputs, schema-validated

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Agent decisions move money-adjacent state (approve, escalate, block). Free-text model
output would require fragile parsing and make programmatic eval assertions (FR-F3)
and rule-citation checks (R-092) unreliable. How are model responses handled?

## Decision Drivers

- Decisions must be programmatically assertable: final action, rule IDs cited,
  tool calls made — the eval suite depends on it (FR-F1, FR-B4).
- Fail-closed doctrine (FR-C5, R-091): malformed output must never be "best-effort
  interpreted" into an action.
- Bounded cost: retries must be limited and budget-counted.

## Considered Options

- Structured outputs: JSON Schema-validated, one bounded retry, then escalate
- Free-text output with regex/heuristic parsing
- Unlimited retries until valid

## Decision Outcome

Chosen option: **structured outputs everywhere**. Tool calls are validated against
the tool's input schema (by the tool gateway); final decisions are validated against
a decision schema (action, rule citations, reasoning). On validation failure the
runtime performs **exactly one retry**, feeding the validation error back to the
model as corrective context. If the retry also fails, the run escalates to a human
with the invalid output attached — fail closed, never guess.

One retry (not zero, not N): a single corrective round fixes the large majority of
schema violations in practice, while unbounded retries burn budget hiding a
systematic prompt/schema mismatch that a human should see.

### Consequences

- Good: eval asserts are exact; traces contain machine-readable decisions; invalid
  model behavior surfaces as escalations (visible) instead of silent misparses.
- Bad: schemas constrain expressiveness — nuanced reasoning must fit declared
  fields; schema evolution is now contract work, versioned like the DNA.
- Bad: one extra model call worst-case per step; counted against the run's budget
  so it cannot compound.
