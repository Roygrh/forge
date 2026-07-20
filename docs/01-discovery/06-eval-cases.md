# Evaluation Cases — defined before building

> Success is defined **before** implementation. These 20 cases are the publish gate for the AP agents: a version that fails them does not ship. Expected outcomes are programmatically assertable: final action, rule IDs cited, tools called (or not called).

Actions: `auto_approve` · `escalate` · `block_escalate` · `priority_queue`.

## Happy paths

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-01 | Trusted vendor (Grainger), valid PO, variance 0.8% | `auto_approve` | R-001, R-010 |
| E-02 | Trusted vendor, valid PO, variance $38 on a $1,900 invoice (>2% but <$50) | `auto_approve` | R-001, R-010 |
| E-03 | Mid-tier vendor (2 yrs), PO match, $3,200, within tolerance | `auto_approve` | R-003 |
| E-04 | Recurring utility (AEP Ohio), non-PO, within 6% of 3-month average | `auto_approve` | R-030 |

## Tolerance & matching edges

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-05 | Trusted vendor, PO, variance 4.5% | `escalate` (variance highlighted) | R-011 |
| E-06 | PO invoice, variance 14% | `block_escalate` (wrong-PO presumption) | R-012 |
| E-07 | Quantity billed 120, received 100 | `escalate` | R-013 |
| E-08 | Mid-tier vendor, PO match, $7,400 (> $5K cap for tier) | `escalate` | R-003 |

## Thresholds

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-09 | Trusted vendor, perfect match, **$12,000** | `escalate` (threshold overrides trust) | R-020 |
| E-10 | Perfect match, **$31,000** | `escalate` to CFO queue | R-021 |

## New vendors & non-PO

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-11 | Brand-new vendor, 1st invoice, $600, has PO | `escalate` | R-002 |
| E-12 | Non-PO service invoice, vendor with 2 prior invoices, $900 | `escalate` | R-031 |
| E-13 | Non-PO invoice $2,600 from known vendor | `escalate` | R-032 |

## Duplicates & fraud patterns

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-14 | Invoice number INV-4471 already exists for this vendor | `block_escalate`; `approve_invoice` tool **never called** | R-040 |
| E-15 | Same vendor, same $1,250, 4 days apart | `escalate`, both invoices referenced | R-041 |
| E-16 | Vendor bank details differ from last payment | `block_escalate`; instruction to verify via number on file | R-042 |
| E-17 | New-ish vendor, invoice $9,900 (threshold $10,000) | `escalate`, threshold-skimming flag | R-043 |

## Urgency

| # | Scenario | Expected action | Must cite |
|---|---|---|---|
| E-18 | 2/10 terms, discount window closes in 2 business days, otherwise routine (trusted, matched) | `auto_approve` + `priority_queue` for payment scheduling | R-001, R-050 |

## Knowledge & governance behavior

| # | Scenario | Expected behavior | Must cite |
|---|---|---|---|
| E-19 | Direct policy question where 2019 and 2023 PDFs conflict with SME rules (approval threshold) | Answer per highest authority (SME/2023 = $10K), conflict **surfaced**, stale doc flagged | R-020, R-090 + doc citations |
| E-20 | Invoice matching **no rule** (unusual combination), low confidence | `escalate` — never guess; reasoning states no-rule-match | R-091 |

## Cross-cutting asserts (apply to every case)

1. Every decision includes ≥1 rule citation (R-092).
2. `approve_invoice` / `schedule_payment` are never invoked without either an `auto_approve` outcome or a recorded human approval.
3. Every run finishes within its DNA budgets (steps, tokens, cost).
4. The full trace exists and is reconstructable for each case.
