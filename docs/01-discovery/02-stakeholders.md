# Stakeholders — Meridian Supply Co. (simulated)

Five personas drive requirements. Each one maps to a platform capability — that mapping is deliberate: every governance feature exists because a specific stakeholder demands it.

---

## Dana Whitfield — CFO (Sponsor)

- **Cares about**: control, auditability, cash discipline. Burned by last year's duplicate payments.
- **Position**: pro-automation, but "no system approves money without me being able to see exactly why, months later."
- **Success criteria**: zero unexplainable payments; capture early-payment discounts; audit trail that satisfies external auditors.
- **Drives requirements for**: immutable audit log, citations, spend thresholds, reporting.

## Rosa Delgado — AP Manager (Domain expert · owner of the tacit rules)

- **Cares about**: cycle time and her team's sanity. Knows every vendor's quirks by heart.
- **Position**: skeptical-positive. "The policy PDF says one thing; how we actually work is another. If your system follows the PDF blindly, it will be wrong by lunchtime."
- **Success criteria**: routine invoices flow without her; she only sees genuine exceptions; the system applies *her* rules, not generic ones.
- **Drives requirements for**: tacit-rule capture (SME process), rule versioning, authority hierarchy over documents.
- **Key risk she names**: "Don't make me approve 60 things a day or I'll stop reading them." → approval-fatigue requirement.

## Kevin Ma — AP Analyst (Primary HITL approver)

- **Cares about**: escaping repetitive matching work; keeping judgment on sensitive cases.
- **Position**: enthusiastic; worried about being blamed for agent mistakes.
- **Success criteria**: when something reaches him, he sees *what* the agent wants to do, *why*, and the evidence — and can decide in under a minute.
- **Drives requirements for**: approval queue UX (proposal + reasoning + context), granular per-action approval, clear accountability trail.

## Priya Nair — Compliance Officer

- **Cares about**: SOX-style control expectations, fraud prevention, data handling.
- **Position**: veto power. "Fail-closed or it doesn't ship."
- **Success criteria**: high-impact actions never autonomous; expired approvals cancel (never auto-approve); every decision reconstructable; vendor-bank-change flows always human-verified.
- **Drives requirements for**: impact classification, fail-closed timeouts, immutable log, fraud-pattern guardrails.

## Tom Barrett — IT Director

- **Cares about**: not adding operational burden to a 3-person IT team; data staying in Meridian's environment.
- **Position**: "If it needs a PhD to run, it's not running here."
- **Success criteria**: containerized deployment he can run on-premise or in their cloud tenancy; model provider swappable (procurement will ask); no credentials scattered around.
- **Drives requirements for**: portability (Docker), LLM gateway with centralized keys, provider-agnostic design.

---

## Influence / interest map

| Stakeholder | Influence | Interest | Strategy |
|---|---|---|---|
| CFO (Dana) | High | High | Sponsor — demo speaks her language (control + savings) |
| Compliance (Priya) | High | Medium | Satisfy early — her constraints are architecture, not features |
| AP Manager (Rosa) | Medium | High | Co-design — her rules ARE the product |
| AP Analyst (Kevin) | Low | High | UX focus — his queue experience decides adoption |
| IT (Tom) | Medium | Medium | Reassure — portability + gateway |

## Communication cadence (simulated engagement)

- Discovery interviews: one per stakeholder (notes in `03-interview-notes.md`)
- Rule-validation session with Rosa after tacit-rule drafting (sign-off recorded in `04-tacit-rules.md`)
- Demo checkpoints at the end of each build iteration, audience-appropriate (Rosa/Kevin see flows; Dana sees the audit view; Tom sees `docker compose up`)
