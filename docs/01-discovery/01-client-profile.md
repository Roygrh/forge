# Meridian Supply Co. — Client Profile (simulated)

> All client data in this repository is synthetic. Meridian is a realistic composite of a mid-market US distributor, designed to exercise every governance capability of the platform.

## Company snapshot

| | |
|---|---|
| Industry | Industrial supplies distribution (MRO: maintenance, repair, operations) |
| HQ | Columbus, Ohio · 3 regional warehouses |
| Revenue | ~$85M / year |
| Employees | ~220 |
| Systems | "MeridianERP" (simulated ERP exposing purchase orders, vendors, GL, payments), shared drive full of policy PDFs of various ages |
| AI maturity | Low — no data team, no prior AI initiatives ("can't spell AI if you spot them the A" segment) |

## The accounts-payable problem

- **Volume**: ~1,400 vendor invoices/month (PDF via email, some paper scans). ~65% reference a purchase order; the rest are non-PO (services, utilities, freight).
- **Team**: 1 AP Manager + 2 AP analysts. Month-end closes are overtime weeks.
- **Cycle time**: average 6.2 days from invoice receipt to approval; vendors call to chase payments; early-payment discounts (2/10 net 30) are almost always missed.
- **Incidents last year**: 2 duplicate payments (~$18K recovered with effort), 1 near-miss on a fraudulent "vendor bank change" email.
- **The real asset**: how invoices *actually* get approved lives in the AP Manager's head — tolerances, vendor trust tiers, when to bend the written policy and when never to. The written policy PDFs are outdated and partially contradictory (v2019 vs v2023 — kept deliberately in this simulation to exercise conflict handling).

## Why Meridian is the right demo client

1. **Money moves** → governance is obviously necessary, HITL has a natural, dramatic use case.
2. **Tacit rules are rich and believable** → perfect substrate for the SME-capture story.
3. **Contradictory documentation is realistic** → exercises authority hierarchy + citations.
4. **Low AI maturity** → the platform must be operable by business users (catalog UI), not by engineers.

## Engagement goal (as Meridian would state it)

> "Cut invoice approval from days to hours without losing control: every automated decision must be explainable, auditable, and reversible — and anything unusual must reach a human before money moves."
