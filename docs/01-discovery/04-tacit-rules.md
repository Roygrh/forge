# Meridian AP — Captured Tacit Rules

| | |
|---|---|
| **Source** | SME interviews (Rosa Delgado, AP Manager; inputs from Kevin Ma, Dana Whitfield, Priya Nair) |
| **Validated by** | Rosa Delgado — sign-off recorded 2026-07-XX (simulated) |
| **Authority** | `sme_validated` — **highest**: overrides all written policy documents on conflict |
| **Version** | 1.0.0 (semver; every change re-validated by owner) |
| **Owner** | AP Manager |

> These rules are the product of the SME-capture process: knowledge that lived in people's heads, made explicit, versioned, and governed. They are ingested as the top-authority knowledge source and referenced by ID in agent decisions and citations.

Legend — **Action** values: `auto_approve` · `escalate` (human review, normal queue) · `block_escalate` (hard stop + human) · `priority_queue`.

## Vendor trust

| ID | Rule | Action |
|---|---|---|
| R-001 | Vendor is **trusted tier** (top-20 list, ≥3 years history, zero disputes) AND valid PO exists AND price variance within tolerance (R-010) | `auto_approve` |
| R-002 | **New vendor** (first 3 invoices ever) — regardless of amount or PO | `escalate` |
| R-003 | Vendor not on trusted tier but >1 year history: PO-matched invoices within tolerance | `auto_approve` up to $5,000; `escalate` above |

## Matching tolerances

| ID | Rule | Action |
|---|---|---|
| R-010 | Price variance vs PO ≤ **2% or ≤ $50** (whichever is greater) → within tolerance | (feeds R-001/R-003) |
| R-011 | Price variance > 2% (or > $50) and ≤ 10% (and ≤ $2,500) | `escalate` with variance highlighted |
| R-012 | Price variance > **10% or > $2,500** → presumed wrong PO, not a tolerance issue | `block_escalate` |
| R-013 | Quantity billed > quantity received (per goods receipt) | `escalate` |

## Amount thresholds (CFO policy — also written, confirmed)

| ID | Rule | Action |
|---|---|---|
| R-020 | Any invoice > **$10,000**, regardless of matching outcome | `escalate` (AP approver) |
| R-021 | Any invoice > **$25,000** | `escalate` to CFO/controller queue |

## Non-PO invoices

| ID | Rule | Action |
|---|---|---|
| R-030 | Recurring utility/rent from known vendor, amount within **±15%** of trailing 3-month average | `auto_approve` |
| R-031 | Non-PO invoice from vendor with <5 prior invoices | `escalate` |
| R-032 | Non-PO invoice > $2,000 (any vendor) | `escalate` |

## Duplicates & fraud guards (hard rules)

| ID | Rule | Action |
|---|---|---|
| R-040 | Invoice number already exists for this vendor | `block_escalate` (possible duplicate/resend) |
| R-041 | Same vendor + same amount within **7 days** of a prior invoice | `escalate` with both shown side by side |
| R-042 | **Vendor bank details changed** since last payment — any channel | `block_escalate`; human verifies by calling the number **on file** |
| R-043 | Amount within **2% under** an approval threshold (e.g., $9,800–$9,999 vs $10K) from non-trusted vendor | `escalate` flagged as threshold-skimming pattern |
| R-044 | Round-number invoice (multiples of $500) from vendor with <1 year history | `escalate` |

## Urgency & cash discipline

| ID | Rule | Action |
|---|---|---|
| R-050 | Early-payment discount terms (e.g., 2/10) and discount window closes within 3 business days | `priority_queue` |
| R-051 | Invoice past due date (vendor chasing) | `priority_queue` |

## Meta-rules (platform behavior)

| ID | Rule |
|---|---|
| R-090 | On any rule conflict: higher authority source wins; same authority → most restrictive action wins |
| R-091 | If no rule matches or confidence below threshold → `escalate` (never guess) — the fail-closed default |
| R-092 | Every decision cites the rule ID(s) applied |

---

## Deliberate policy conflicts (for the knowledge-layer demo)

The simulated document set includes `AP-Policy-2019.pdf` (three-way match mandatory for ALL invoices; approval threshold $5,000) and `AP-Policy-2023.pdf` (threshold $10,000; trusted-vendor exception). R-001 vs the 2019 policy, and R-020 vs the 2019 threshold, are **intentional conflicts**: the demo shows authority-ranked retrieval resolving them (sme_validated > policy_2023 > policy_2019) with citations — and the remediation loop flagging the stale document to its owner.
