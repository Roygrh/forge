# Sequence — Guardrail block (duplicate & no-rule-match)

Two fail-closed outcomes, side by side. A duplicate invoice number is a **hard rule**
(R-040 → `block_escalate`, case E-14): the run stops and `approve_invoice` is never
called. An invoice matching **no rule** at low confidence (R-091 → `escalate`, case
E-20) is the same doctrine from the other direction: never guess, never execute. In
both, no money-moving tool is invoked and the decision cites the rule that fired.

```mermaid
sequenceDiagram
    participant Runtime
    participant ToolGW
    participant KB
    participant LLMGW
    participant DB

    Runtime->>ToolGW: Gather evidence (read_invoice, get_vendor)
    ToolGW-->>Runtime: Invoice + vendor facts (incl. invoice-number history)
    Runtime->>KB: Retrieve applicable rules
    alt Duplicate invoice number INV-4471 (R-040, E-14)
        KB-->>Runtime: R-040 matches (hard duplicate rule)
        Runtime->>LLMGW: Decide (schema-constrained)
        LLMGW-->>Runtime: block_escalate, cites R-040
        Note over Runtime,ToolGW: approve_invoice is NEVER invoked
        Runtime->>DB: Append decision block_escalate (R-040) + escalation
    else No rule matches / low confidence (R-091, E-20)
        KB-->>Runtime: No rule matches
        Runtime->>LLMGW: Decide (schema-constrained)
        LLMGW-->>Runtime: escalate, reason = no-rule-match
        Note over Runtime,ToolGW: Fail closed — never guess, never execute
        Runtime->>DB: Append decision escalate (R-091)
    end
    Runtime->>DB: Append run.completed (awaiting human)
```

## What to notice

- **Hard rule stops the run** — R-040 is `block_escalate`: the decision is a full stop
  plus human escalation, not a queued action (tacit rules, duplicates & fraud guards).
- **`approve_invoice` never fires (E-14 assert)** — the note over Runtime/ToolGW marks
  the exact invariant the eval case asserts: the money-moving tool is not called.
- **No-rule-match is not "figure it out"** — the `else` branch is R-091 / ADR-006's
  fail-closed default: absence of a matching rule forces `escalate`, with the reasoning
  stating no-rule-match (E-20).
- **The decision still cites a rule** — even a block or a no-match cites R-040 / R-091,
  so `require_citations` (R-092) holds for guardrail outcomes too.
- **Both outcomes are traced** — the block and the escalation are appended events,
  reconstructable like any other run (ADR-008, FR-G1).
