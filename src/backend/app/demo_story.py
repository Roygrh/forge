"""The demo story: five runs, in order, that explain the platform to someone new.

Phase 6.1 adds no capability. It adds a *reading order* over what already exists, so a
presenter with ten minutes and an audience that has never seen Forge does not have to
hunt for the right invoice mid-sentence.

Nothing here invents data. Every beat names a record that was already in
:mod:`app.erp.seed_data`, put there for an eval case (``docs/01-discovery/06-eval-cases.md``)
and frozen ever since. The contribution of this module is the *curation*: which five
runs, in which order, under which label, and what each one is supposed to land. That is
why the beats carry ``expect`` and ``cites`` — the observed outcome of the run, verified
by :mod:`tests.test_demo_story` against the same dataset the runtime reads, so the demo
script cannot quietly stop being true.

The narrative is deliberate:

1. **Clean** — it works, and it says which rules let it.
2. **Threshold** — same vendor, same quality of match, over policy. Trust does not beat
   policy.
3. **Duplicate** — the platform stops, and the write tool is never called.
4. **Human** — the action is composed, parked, and released by a person.
5. **Conflict** — three sources answer the same policy question differently; authority
   decides, and the loser stays visible.

Beats 1–3 and 5 run the validator, so the audience watches one agent behave differently
because the *facts* differ — not because someone wrote four code paths.

``docs/demo-script.md`` is the presenter-facing form of this module, and
``src/frontend/src/lib/story.ts`` is its mirror in the SPA (hand-mirrored, the same
convention as ``api/types.ts`` against ``app/api/schemas.py``). If you change a beat,
change all three.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.evals.catalog import E19_QUESTION

#: The question the comms agent is sent to ask about INV-4405, verbatim. It concerns a
#: price difference rather than bank details, so the agent's own instructions leave the
#: channel to it — and it picks ``phone_on_file``, which is worth pointing at.
COMMS_QUESTION = "Which purchase order covers the price difference on this invoice?"


@dataclass(frozen=True)
class DemoRun:
    """One labelled, pre-composed run a presenter can start without typing anything."""

    #: Position in the five-beat story, or ``None`` for a supporting run that is worth
    #: having a button for but is not part of the narrated sequence.
    beat: int | None
    #: Stable identifier. Used as the option value in the SPA and in the demo script.
    key: str
    #: What the presenter reads in the picker. Leads with the invoice number (or the
    #: word "Policy") because that is what they will be saying out loud.
    label: str
    #: The one line this run exists to land.
    point: str
    #: The agent this run is started against.
    agent_slug: str
    #: Exactly what is sent as the run input.
    input: Mapping[str, str]
    #: The MeridianERP invoice the run is about, when there is one.
    invoice_id: str | None
    #: The terminal run status observed, verbatim from the API.
    expect_status: str
    #: The final action the agent decided, or ``None`` when the platform stopped the run
    #: before a decision (the restricted validator) or parked it (comms).
    expect_action: str | None
    #: The rule and document citations the decision carried, in the order recorded.
    cites: tuple[str, ...]


def _run(
    *,
    beat: int | None,
    key: str,
    label: str,
    point: str,
    agent_slug: str,
    input: Mapping[str, str],
    invoice_id: str | None,
    expect_status: str,
    expect_action: str | None,
    cites: tuple[str, ...] = (),
) -> DemoRun:
    return DemoRun(
        beat=beat,
        key=key,
        label=label,
        point=point,
        agent_slug=agent_slug,
        input=MappingProxyType(dict(input)),
        invoice_id=invoice_id,
        expect_status=expect_status,
        expect_action=expect_action,
        cites=cites,
    )


#: Every pre-composed run the SPA offers, story beats first, in presentation order.
DEMO_RUNS: tuple[DemoRun, ...] = (
    _run(
        beat=1,
        key="clean",
        label="INV-4401 — clean approval",
        point="It works — and it tells you which rules let it.",
        agent_slug="invoice-validator",
        input={"invoice_id": "inv-0001"},
        invoice_id="inv-0001",
        expect_status="completed",
        expect_action="auto_approve",
        cites=("R-001", "R-010"),
    ),
    _run(
        beat=2,
        key="threshold",
        label="INV-4409 — $12,000, over policy",
        point="Same vendor, same perfect match. Trust does not beat policy.",
        agent_slug="invoice-validator",
        input={"invoice_id": "inv-0009"},
        invoice_id="inv-0009",
        expect_status="escalated",
        expect_action="escalate",
        cites=("R-001", "R-010", "R-020", "R-090"),
    ),
    _run(
        beat=3,
        key="duplicate",
        label="INV-4471 — duplicate invoice number",
        point="It stopped, and approve_invoice was never called.",
        agent_slug="invoice-validator",
        input={"invoice_id": "inv-0015"},
        invoice_id="inv-0015",
        expect_status="escalated",
        expect_action="block_escalate",
        cites=("R-001", "R-010", "R-040", "R-090"),
    ),
    _run(
        beat=4,
        key="human",
        label="INV-4405 — ask the vendor (needs a person)",
        point="The message is written, and it is not sent. A person decides.",
        agent_slug="invoice-comms",
        input={"invoice_id": "inv-0005", "question": COMMS_QUESTION},
        invoice_id="inv-0005",
        expect_status="awaiting_approval",
        expect_action=None,
        cites=(),
    ),
    _run(
        beat=5,
        key="conflict",
        label="Policy question — which approval threshold governs?",
        point="Three sources disagreed. Authority decided, and the loser stays on the record.",
        agent_slug="invoice-validator",
        input={"question": E19_QUESTION},
        invoice_id=None,
        expect_status="completed",
        expect_action="auto_approve",
        cites=(
            "R-020",
            "AP-Policy-2023.pdf#approval-thresholds",
            "AP-Policy-2019.pdf#approval-thresholds",
            "R-090",
        ),
    ),
    # --- Supporting runs: a button worth having, not a beat of the narration ----
    _run(
        beat=None,
        key="intake",
        label="INV-4401 — normalise for validation",
        point="Intake may read an invoice and nothing else.",
        agent_slug="invoice-intake",
        input={"invoice_id": "inv-0001"},
        invoice_id="inv-0001",
        expect_status="completed",
        expect_action="auto_approve",
        cites=("R-092",),
    ),
    _run(
        beat=None,
        key="revoked",
        label="INV-4401 — the same invoice, approval revoked",
        point="One line of the definition changed, and the gateway refuses the call.",
        agent_slug="invoice-validator-restricted",
        input={"invoice_id": "inv-0001"},
        invoice_id="inv-0001",
        expect_status="escalated",
        expect_action=None,
        cites=(),
    ),
)

#: The five beats, in order — the sequence ``docs/demo-script.md`` narrates.
DEMO_STORY: tuple[DemoRun, ...] = tuple(run for run in DEMO_RUNS if run.beat is not None)


def runs_for(agent_slug: str) -> tuple[DemoRun, ...]:
    """The pre-composed runs offered for one agent, in presentation order."""
    return tuple(run for run in DEMO_RUNS if run.agent_slug == agent_slug)
