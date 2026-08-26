# Forge — 10-minute demo script

> Two complete versions of the same ten minutes: **[Technical](#technical-version)** for an
> engineer, **[Business](#business-version)** for someone who will never open a terminal.
> Both walk the same five beats against the same seeded data, so a mixed room can be given
> either one without changing anything on the screen.
>
> Everything here has been executed against a freshly composed stack and says what actually
> happened. `src/backend/tests/test_demo_story.py` runs every beat through the real runtime
> on each build and asserts the outcome — if this document ever stops being true, the build
> fails before the audience does.

---

## The story in one table

Five runs, in this order. They are pre-composed: the **Case to run** picker on each agent
card in the catalog already holds them, labelled, so nothing has to be typed or looked up
mid-sentence.

| # | Pick this case | On this agent | What happens | The line that lands it |
|---|---|---|---|---|
| 1 | `1. INV-4401 — clean approval` | Invoice Validator | `completed` · **auto_approve** citing R-001, R-010 | "It works — and it tells you which rules let it." |
| 2 | `2. INV-4409 — $12,000, over policy` | Invoice Validator | `escalated` · **escalate** citing R-001, R-010, **R-020, R-090** | "Same vendor, same perfect match. Trust does not beat policy." |
| 3 | `3. INV-4471 — duplicate invoice number` | Invoice Validator | `escalated` · **block_escalate** citing R-001, R-010, **R-040**, R-090 — and `approve_invoice` is never called | "It stopped, and the write tool was never even asked for." |
| 4 | `4. INV-4405 — ask the vendor (needs a person)` | Invoice Comms | `awaiting_approval` — the message is drafted, validated, and **not sent** | "The message is written, and it is not sent. A person decides." |
| 5 | `5. Policy question — which approval threshold governs?` | Invoice Validator | `completed` · answered per authority, **both conflicts shown on screen** | "Three sources disagreed. Authority decided, and the loser stays on the record." |

Beats 1, 2, 3 and 5 are the **same agent, same version**. Nothing about it changes between
them — only the facts do. That is the whole argument, and it is worth saying out loud once.

---

## Pre-flight

Do this **before** the audience is in the room. Total: about three minutes, most of it the
first image build.

```bash
cd deploy
docker compose down -v                 # discard any state from a rehearsal
docker compose up -d --build --wait    # ~2-3 min cold, ~40 s warm
```

`--wait` is the point: the command does not return until every container reports
**healthy**, and the API's healthcheck *is* the readiness probe — so when your prompt comes
back, the schema is at head, the seed has run, and the catalog has something published to
execute. Then verify, in this order:

| # | Check | Command | What you must see |
|---|---|---|---|
| 1 | The API is ready | `curl http://localhost:8000/api/v1/ready` | `{"status":"ready","checks":{"database":"ok","migrations":"ok","seed":"ok"},...}` — anything else, see [Recovery](#recovery). |
| 2 | The seed installed the story | `docker compose logs migrate` | `22` rules, `32` knowledge chunks, `20` eval cases, four published agents, then `demo story: 5 beats, in presentation order` and the five labels. If the beats are not listed, the running image is older than this script. |
| 3 | The UI loads | open <http://localhost:5173> | Four agent cards, each with a **Case to run** picker. |
| 4 | Beat 1 really approves | press **Run** on Invoice Validator with case 1 selected | `Completed` · `Auto approve` · citations `R-001` `R-010`. |
| 5 | **Reset the ERP** | `docker compose restart api` (~10 s) | Not optional — see the warning below. |

> **⚠ Rehearse, then restart the API.** MeridianERP is stateful on purpose: an invoice
> approved by one run *is* approved, and approving it a second time is refused — which is
> the duplicate-payment control working, but it is not the beat you want live. Restarting
> the `api` container rebuilds the simulated ERP from its seed, so beat 1 approves cleanly
> again. **Restart `api` after every rehearsal**, and after any live run of beat 1 you
> intend to repeat. `docker compose restart api` is enough; you do not need to touch the
> database, and nothing in the audit log is lost — it lives in PostgreSQL, not in the
> simulated ERP.

Last: set the role selector in the header to **Configurator**, and open the browser at `#/`
(the catalog). Do not pre-run beat 4 — the approval queue should be empty when you arrive at it.

On a fresh stack the **Evals** screen correctly reads *No eval run for this version yet*: the seeded
versions are published by the seed script, which is the one documented exception to the gate. Leave
it that way and press **Run suite** live — it scores all twenty cases in about a second, and an empty
screen filling with 20 green rows in front of the audience is worth more than a pre-baked one.

---

## Technical version

For someone who will ask what happens when the model is wrong.

Stay as **Configurator** throughout except for the approval at 8:35, and switch back before the
Evals screen at 9:10. The Approver role holds `read` and `approval.decide` and nothing else — it
cannot start a run and cannot score a suite. That is the segregation of duties working, but it is
a 403 you want to demonstrate deliberately at 8:10, not trip over at 9:10.

| At | What to click | What to say | Point at | The beat |
|---|---|---|---|---|
| **0:00** | Nothing — the catalog is already open | "Forge is an agent *factory*. An agent here isn't a service somebody wrote; it's a JSON document — its DNA — and one runtime executes all of them. Governance isn't a feature on top: an agent can only ever do what its document declares." | The four cards, then one card's **Tools granted** column | "One runtime, N agents, and the permissions live in the artifact." |
| **0:30** | Stay on **Invoice Validator** — just read the card | "Everything on this card is read from the published DNA: the model it's pinned to, every tool it's granted and at what autonomy, its step ceiling. Note `schedule-payment` is granted **forbidden** — the permission was considered and denied, and that's in the document, not in a code-review comment." | The red `forbidden` pill on `meridian-erp-schedule-payment@1.0.0`; the amber `requires approval` pill on `request-info-from-vendor` | "Least privilege is a line in the artifact, not a convention." |
| **1:30** | Case picker → **`1. INV-4401 — clean approval`** → **Run** | "Routine invoice. Trusted vendor, valid PO, sub-1% price variance. Watch what it leaves behind." | The status pill **Completed** | — |
| **2:00** | Scroll the run trace | "Six trips through the tool gateway — read the invoice, the vendor, match the PO, the goods receipts, then *retrieve the rules*. The agent contains no rules. It asks for the ones that apply and reasons over what came back." | The tool steps, then the green **Decision** card: `Auto approve`, citations **R-001 R-010**, and in the reasoning `match.price_variance_pct lte 2 (actual: '0.80')` | "The citation isn't a summary. It's the rule ID and the fact it matched on." |
| **2:45** | Expand **Raw events** at the bottom | "That timeline is a projection. This is the append-only log it came from — `run.started`, `model.called`, `tool.called`, `decision.made`. There is no UPDATE or DELETE grant on that table, and `GET /runs/{id}/trace` rebuilds the whole run from these alone." | The monotonic `event_id` ordering | "The screen isn't asking to be believed." |
| **3:30** | Back to **Agents** → case **`2. INV-4409 — $12,000, over policy`** → **Run** | "Same agent, same version, same vendor. A *better* match this time — zero variance. And it escalates." | Status **Escalated**; the **Escalate** decision pill | — |
| **4:00** | The decision card's reasoning | "Read the last sentence: *R-020 decides escalate, which is the most restrictive of the actions proposed (auto_approve, escalate) under R-090.* Two rules fired with different answers. R-090 is the meta-rule — equal authority, most restrictive wins — and it's cited, so the conflict resolution is auditable too." | Citations **R-001 R-010 R-020 R-090**; the final sentence of the reasoning | "Trust doesn't beat policy, and the platform shows its arithmetic." |
| **4:45** | Case **`3. INV-4471 — duplicate invoice number`** → **Run** | "Same invoice number this vendor already billed, and was paid for, in June. This is the beat that pays for the whole platform." | The **Block escalate** decision pill; citations including **R-040** | — |
| **5:15** | Count the tool steps | "Five tool steps. There is no sixth. `approve_invoice` was never called — not blocked, not refused, *never asked for*, because the rule that fired forbids the action outright. And that tool handler is invoked in exactly one place in the codebase; a test reads the source tree to keep it that way." | The absence of an `approve-invoice` step, against beat 1 where it executed | "Nothing moved — and you can prove nothing moved." |
| **6:00** | Case **`5. Policy question — which approval threshold governs?`** → **Run** | "Not an invoice — a question, to the same agent. It also has a knowledge tool, over three sources: the SME-validated rules, the 2023 policy PDF, and the 2019 one nobody ever retired." | The single `meridian-knowledge-retrieve` tool step | — |
| **6:30** | The retrieval step's evidence panel | "Hybrid retrieval — Postgres tsvector plus embeddings, RRF-fused — then the authority hierarchy: SME-validated beats 2023 beats 2019. It found *two* conflicts, not one. The 2019 document says $5,000; R-020 says $10,000. The loser is struck through and kept, and flagged to its owner for remediation." | The amber **⚖ SOURCES DISAGREED** banner on `approval_threshold`, the pill `resolved by authority (R-090)`, the ✓ **governed** card (R-020, `$10,000`) beside the **superseded** card (`AP-Policy-2019.pdf#approval-thresholds`, `$5,000`) | "It didn't take the top search hit. It applied a declared hierarchy and showed you what lost." |
| **7:00** | The decision card | "Four citations: the rule, *both* documents, and R-090 for the resolution. The § badges name a document section a human can open. That's the difference between a citation and a footnote." | The blue `§` citation badges | — |
| **7:20** | **Agents** → **Invoice Comms** → case **`4. INV-4405 — ask the vendor (needs a person)`** → **Run** | "Its only tool is granted `requires_approval`. So the run doesn't fail and doesn't send — it parks." | Status **Awaiting approval**; the amber tool step: *validated*, result **None — the call is waiting on a human approval** | — |
| **7:50** | **Approvals** in the header | "Everything the agent gathered arrives with the item, so a reviewer needs no second tab. And look at the channel it chose: `phone_on_file`, not a number off the invoice. That's R-042's rule about verifying bank changes, applied unprompted." | The proposed action, its exact `args`, the deadline (eight working hours) | — |
| **8:10** | Press **✓ Approve** while still acting as **Configurator** | "403. The role that configures an agent is structurally never the role that approves what it proposes — a permission matrix the build refuses to start without. And the refusal is in the audit log: the attempt is recorded, not just declined." | The red `permission_denied` error naming `approval.decide` | "Segregation of duties, enforced by the server — not by a greyed-out button." |
| **8:35** | Header role → **Approver** → **✓ Approve** with a note → **Open the trace →** | "Now it resumes — by replaying its own event log, not from a session someone was holding in memory. And the executed call is stamped with who released it." | On the tool step: **Released by role:approver — this call ran only because a person approved it** | "An action a person signed for never reads like one the agent took alone." |
| **9:10** | Switch the header role back to **Configurator**, then **Evals** | "Twenty cases, written during discovery *before* the agents existed. Each one executes a real run of the version under test — offline, deterministic — scored by programmatic asserts: final action, cited rule IDs, tools called and not called. `POST .../publish` answers **409** until this exact version has a passing run of the suite its own DNA names. The button is a courtesy; the 409 is the control." | Press **Run suite** — it scores all twenty in about a second — then the case table and the **Publish gate** panel | "Nothing ships without passing its evals, and the passing run is recorded as the publish's evidence." |
| **9:40** | Close | "All of that ran with no API key and no network: the provider is one line in the DNA. Swapping `fake` for `anthropic`, and MeridianERP's Python for an HTTP client, are the two changes that make it real — nothing above the tool layer knows the difference. What doesn't change is the part that took the work: the contract, the gateway, the log, and the gate." | — | "The demo is offline so it can't fail. The architecture is the same either way." |

**Footnote for a sharp audience.** In beat 5 the run's recorded action is `auto_approve`. The
platform has exactly four final actions, and a successfully answered question is recorded as
the permissive one — nothing was posted, and the validator has no tool that could post it. It
is a vocabulary artefact, documented in `app/evals/catalog.py`. If someone spots it, say so;
owning it lands better than deflecting.

**And know how beat 4 ends.** After the approver releases it, the message *is* sent and the
run then finishes `escalated`, citing **R-091** — with a red governance banner reading
`no_rule_match`. That is correct and it is the point: the invoice is unresolved until the
vendor answers, so the platform hands it to a human rather than guessing. Get ahead of the
red banner rather than letting it read as a failure: *"it sent the question and then refused
to decide the invoice, because nothing has come back yet."*

---

## Business version

For someone who signs the invoice, not the pull request. Same clicks, different words. Say
"the system", never "the runtime".

The order differs from the technical version on purpose: the human-in-the-loop beat comes
**last**, so the room leaves on "a person decides" — and so the one role switch happens once,
at 8:15, and never has to be undone. Stay as **Configurator** until then. (The Approver role
holds `read` and `approval.decide` and nothing else, so it genuinely cannot start a run — if
you switch early you will be looking at a 403 instead of a beat.)

| At | What to click | What to say | Point at | The beat |
|---|---|---|---|---|
| **0:00** | The catalog | "Meridian Supply processes a few thousand supplier invoices a month, and today a person reads every one. This is four software agents doing that work — and the reason you'd let them is on this screen." | The four cards | "The point isn't that it's automated. It's that it's governed." |
| **0:30** | One card's middle column | "Each agent has a written charter, and the system physically cannot exceed it. This one may approve an invoice up to a ceiling. It may *not* schedule a payment — that's marked forbidden. Nobody has to remember that; the system won't do it." | **Tools granted**, and the red `forbidden` label | "Its permissions are the product, not a policy document." |
| **1:15** | Case **`1. INV-4401 — clean approval`** → **Run** | "A routine invoice from a supplier of eight years, against a purchase order, priced within a percent. This is roughly seven out of ten of what your team touches." | Status **Completed**; the green **Auto approve** | — |
| **1:45** | The decision card | "Approved in under a second — and here's what matters: it says *why*. Rule R-001, trusted supplier with a matched order. Rule R-010, price within tolerance. Those are Rosa's own rules, written down during discovery and now living inside the system. Anyone can audit that decision in ten seconds." | The **Citations** block: `R-001` `R-010` | "Cycle time goes from days to a second — and the reason stays readable." |
| **2:40** | Case **`2. INV-4409 — $12,000, over policy`** → **Run** | "Same supplier. Same clean paperwork. Twelve thousand dollars instead of four. And it stops." | Status **Escalated** | — |
| **3:10** | The reasoning | "Your CFO's threshold is ten thousand, and no amount of supplier goodwill overrides it. When two rules disagree, the system takes the *more restrictive* one — always. That's a rule too, and it's cited." | The four citations, ending in `R-090` | "Trust doesn't beat policy. Ever, and not by accident." |
| **4:00** | Case **`3. INV-4471 — duplicate invoice number`** → **Run** | "This is the resend of an invoice you already paid in June. It's the most common way money leaves a company twice, and it's usually nobody's fault — it's a busy Tuesday." | The **Block escalate** decision, citation `R-040` | — |
| **4:30** | The list of tool steps | "Look at what the system actually *did*: it read, it checked, it stopped. The approval function was never called. Not attempted and blocked — never called. One bad automated payment erases a year of the savings the first beat earns you, and this is the beat that prevents it." | The steps — and the absent approval step | "Every dollar the first beat saves is only real because this one exists." |
| **5:25** | Case **`5. Policy question — which approval threshold governs?`** → **Run** | "Now something different. I'm asking the system a policy question that your own documents answer three different ways — this is the one your compliance officer will care about." | The **⚖ SOURCES DISAGREED** banner | — |
| **5:55** | The two source cards | "Your 2019 policy says five thousand. Your 2023 policy and Rosa's validated rules say ten. The system doesn't guess and doesn't average — it applies a hierarchy you declared, answers ten thousand, and *shows you the document it overruled*, flagged back to the CFO's office to be retired. It found a stale policy nobody had noticed." | The ✓ **governed** card ($10,000) beside the **superseded** card ($5,000) | "It didn't just answer. It found a contradiction inside your own policies." |
| **7:00** | **Agents** → **Invoice Comms** → case **`4. INV-4405 — ask the vendor (needs a person)`** → **Run** | "Last beat, and it's the one that decides whether your team will accept this. Sometimes the invoice simply doesn't have enough information. This agent writes to the supplier — and it is not allowed to press send." | Status **Awaiting approval** | — |
| **7:30** | **Approvals** in the header | "Here's the queue your AP analyst works. The exact message, the invoice it's about, and everything the agent looked at — no second screen, no ERP tab. And notice it wants to call the number *on file*, not the one printed on the invoice: that's your anti-fraud habit, made explicit." | The proposed message, its arguments, the deadline | — |
| **8:15** | Point at the deadline. Then switch the header role to **Approver**, press **✓ Approve** with a note, and click **Open the trace →** | "If nobody answers within eight working hours, it doesn't go out — the request is cancelled. Silence is never a yes, and there is no button anywhere to extend it. Now I'll release it, and the record will say a person did, by name." | The **Released by** line on the resumed run | "Nobody has to do anything for the safe outcome. That is what 'fail closed' means." |
| **9:05** | **Metrics** in the header | "And it's measured. What share was approved without a human, what share escalated, what each run cost — all computed from the audit log, not from a counter somebody could reset." | The auto-approval and escalation rates, and the cost figures | — |
| **9:40** | Close | "Nothing here needed an internet connection or a cent of model spend — that's deliberate for a demo. To run it against your real ERP: connect the read side, keep this approval queue exactly as it is, and start the agents in *suggest* mode so your team sees what they would have decided before they decide anything. That's weeks, not quarters — and the governance is already built, because it was built first." | — | "You don't have to trust it. You have to be able to check it — and you just did, five times." |

---

## Recovery

Things that can go wrong live, and the thirty-second answer to each.

| Symptom | Almost certainly | Do this |
|---|---|---|
| Beat 1 ends **Escalated** with a red *tool failed* step mentioning `is approved` | The ERP still remembers a rehearsal: INV-4401 was already approved | `docker compose restart api`, wait ~10 s, re-run. Then say it out loud — "the ERP refuses to approve the same invoice twice, which is the control working." It is a recovery *and* a talking point. |
| The UI shows *Could not reach the Forge API* | The API container is restarting, or `CORS_ORIGINS` was overridden | `docker compose ps` — if `api` is not `healthy`, `docker compose logs api --tail 50`. `curl http://localhost:8000/api/v1/ready` names the check that failed. |
| `/ready` answers **503** with `"migrations":"stale"` | The image is newer than the schema in the volume | `docker compose up -d --build` again; the one-shot `migrate` container re-runs and the API waits for it. |
| The catalog is empty | The seed did not run | `docker compose logs migrate` says why. `docker compose exec api python -m scripts.seed` re-runs it — it is idempotent. |
| The approval queue is empty at beat 4 | You are looking before the run parked, or the run already ended | Press **Refresh** on the Approvals screen. If the run reads `Canceled`, the approval expired — start beat 4 again. |
| A run is slower than expected | Nothing — the first run in a fresh container pays import cost | Keep talking. Every run after that is sub-second. |
| Something is genuinely broken and you have ninety seconds | — | `cd deploy && docker compose down -v && docker compose up -d --build --wait`. It comes back migrated, seeded and working with no follow-up commands, and the command blocks until it is genuinely ready — which is itself worth narrating. |

**Why none of this is likely.** The shipped agents name a deterministic, in-process model
provider in their DNA. There is no API key, no network call, no rate limit, no sampling, and
no model outage between you and the audience: the same invoice produces the same decision,
byte for byte, on every machine and every day — the seeded ERP even has a fixed idea of what
today is, so "the discount window closes in two days" is still true a year from now. If a
beat ever changes behaviour, it changed because someone changed the rules or the code, and
the test suite will have said so first. **Say this out loud during the technical version** —
an evaluator who has watched a live LLM demo fail will recognise the choice immediately.

---

## Closing the loop: what a real deployment would take

Worth having ready, because it is the first question after the demo ends.

| To make real | What changes | What does not |
|---|---|---|
| **The model** | One line per agent: `"provider": "fake"` → `"anthropic"`, plus `ANTHROPIC_API_KEY` in the environment. Each DNA already declares its own token, per-run and per-day cost ceilings, and the runtime enforces them. | The runtime, the gateway, the trace, the evals. Nothing above the adapter layer knows which provider answered. |
| **The ERP** | `app/erp/store.py` becomes an HTTP client instead of an in-process simulation. The tool contracts it sits behind do not move. | Every rule, every fact name, every citation. The agents never talked to the ERP — they talked to seven typed tools with typed contracts. |
| **The rules** | Rosa edits rows in the `rules` table (or a screen over it). Lower a threshold with one `UPDATE` and the next run decides differently. | No code change, no rebuild, no redeploy. This already works today — it is the spare beat if you have time. |
| **Going live safely** | Publish the agents with `approve_invoice` granted `requires_approval` instead of `autonomous`. Every decision then lands in the queue with its reasoning, and the team compares the agent's call with their own for a few weeks. The autonomy report on the Approvals screen measures the agreement rate. | Raising autonomy afterwards means publishing a new DNA version — through the eval gate. A statistic never widens a permission on its own. |
| **Everything else** | Real authentication instead of the `X-Forge-Role` header; secrets out of the env file; the SPA behind SSO. | The segregation-of-duties matrix itself, which is already a permission matrix the build refuses to start without. |

---

## Appendix — the exact runs, for scripting or a backup video

Every beat as an API call, in order. Useful for recording a backup video, for a headless
rehearsal, or if the SPA is unavailable. Every request carries `X-Forge-Role`.

```bash
API=http://localhost:8000/api/v1
ROLE='X-Forge-Role: configurator'
VALIDATOR=$(curl -s -H "$ROLE" $API/agents | python -c \
  "import json,sys;print([a['id'] for a in json.load(sys.stdin) if a['slug']=='invoice-validator'][0])")

run() { curl -s -X POST $API/runs -H "$ROLE" -H 'Content-Type: application/json' -d "$1"; }

# 1 - clean            -> completed  · auto_approve   · R-001, R-010
run "{\"agent_id\":\"$VALIDATOR\",\"version\":\"1.2.0\",\"input\":{\"invoice_id\":\"inv-0001\"}}"
# 2 - over threshold   -> escalated  · escalate       · R-001, R-010, R-020, R-090
run "{\"agent_id\":\"$VALIDATOR\",\"version\":\"1.2.0\",\"input\":{\"invoice_id\":\"inv-0009\"}}"
# 3 - duplicate number -> escalated  · block_escalate · R-001, R-010, R-040, R-090
run "{\"agent_id\":\"$VALIDATOR\",\"version\":\"1.2.0\",\"input\":{\"invoice_id\":\"inv-0015\"}}"
# 5 - policy conflict  -> completed  · answered per authority, both conflicts recorded
run "{\"agent_id\":\"$VALIDATOR\",\"version\":\"1.2.0\",\"input\":{\"question\":\"What is the invoice approval threshold amount requiring manager approval?\"}}"
# 4 - needs a person   -> awaiting_approval; then GET /approvals and approve as the approver role
```

The five beats are defined once, in `src/backend/app/demo_story.py`, mirrored for the SPA in
`src/frontend/src/lib/story.ts`, and asserted end to end by
`src/backend/tests/test_demo_story.py`. The invoices they name were already frozen in
`src/backend/app/erp/seed_data.py` — every one was put there for an evaluation case in
`docs/01-discovery/06-eval-cases.md`, which is why the story and the publish gate cannot
drift apart.
