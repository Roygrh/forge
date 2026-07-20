# Discovery Interview Notes (simulated)

> Method: structured 45-minute interviews per stakeholder. Goal: surface the rules that are **not** in any document. Quotes are the raw material; the distilled, validated rules live in `04-tacit-rules.md`. This process is itself part of the demonstration: it is the SME-capture workflow at small scale.

---

## Interview 1 — Rosa Delgado, AP Manager

**On how approval actually works:**
> "The PDF says every invoice needs three-way match. Reality: for Grainger, Fastenal, our top twenty vendors — if there's a PO and the difference is under a couple percent, it goes through. I haven't hand-checked a Grainger invoice in three years and nothing bad ever happened."

> "New vendor? Different story. First three invoices from anyone new, I look at personally. No exceptions. That one IS a rule, even if it's written nowhere."

**On tolerances:**
> "Price difference under 2% or under $50, whichever is bigger — nobody cares, freight and rounding. Over that, somebody has to look. Over 10% or over $2,500 difference, that's not a tolerance problem, that's a wrong-PO problem."

**On non-PO invoices:**
> "Utilities and rent, monthly, same ballpark amount — wave them through if they're within, say, 15% of last month. A service invoice with no PO from a vendor we barely use? That goes up, always."

**On urgency and discounts:**
> "If the invoice has 2/10 terms and we're inside the window, it jumps the queue. Missing those discounts is literally burning money — Dana's words."

**On what must never be automatic:**
> "Anything where the vendor's bank details changed. We almost got burned. A human calls the vendor at the number WE have on file — not the one in the email — every single time."

---

## Interview 2 — Kevin Ma, AP Analyst

**On his day:**
> "Eighty percent of my time is matching lines and chasing POs. The judgment part — the weird ones — is maybe ten invoices a day. I'd keep those happily."

**On what he needs to approve fast:**
> "Show me: what it wants to do, the invoice, the PO next to it, which rule fired, and what's off. If I have to open the ERP in another tab, that's two more minutes each."

**On duplicates:**
> "Same vendor, same amount, within about a week — siren goes off in my head. Same invoice number ever — hard stop. Vendors resend PDFs all the time and it looks like a new invoice if you're not careful."

---

## Interview 3 — Dana Whitfield, CFO

**On control:**
> "I don't need to see every invoice. I need to KNOW I could reconstruct any of them. Auditors ask 'why was this paid' — the answer can't be 'the AI decided.'"

**On thresholds:**
> "Anything over $10,000 gets human eyes regardless of how routine it looks. Over $25,000, it's me or the controller. That's non-negotiable and it's actually written somewhere, for once."

**On value:**
> "Six days to approve is embarrassing. Get routine invoices to same-day and capture the 2/10 discounts, and this project pays for itself. But one bad automated payment erases a year of savings — that's the asymmetry you're designing for."

---

## Interview 4 — Priya Nair, Compliance

**On non-negotiables:**
> "Approvals expire. If nobody acted, the answer is no — the system never defaults to yes. And the log is append-only: nobody edits history, including admins."

> "Segregation of duties: whoever configures an agent's rules can't also be the sole approver of that agent's actions. Keep the roles distinct even in the demo."

**On fraud patterns:**
> "Bank-detail changes, invoices just under approval thresholds — like $9,900 when the threshold is $10,000 — round-number invoices from new vendors. Those patterns escalate, always."

---

## Interview 5 — Tom Barrett, IT Director

**On deployment:**
> "Give me containers and a compose file, I'm happy. If procurement later says 'we got a better deal with another AI provider,' swapping should be a config change, not a project."

**On credentials:**
> "One place holds the API keys. Not sprinkled in every agent. We rotate quarterly."

---

## Synthesis — what discovery changed

1. The **written policy is not the truth** — Rosa's operational rules override the PDFs → authority hierarchy with SME-validated rules at the top.
2. **Asymmetric risk** (Dana): design optimizes for "never a bad payment," then for speed → fail-closed everywhere.
3. **Approval fatigue is a named risk** (Rosa) → autonomy promotion with evidence is a requirement, not a nice-to-have.
4. **Concrete fraud patterns** (Priya, Rosa) become guardrails with tests, not vague "security."
5. **Portability and provider-agnosticism** (Tom) confirm the LLM-gateway decision.
