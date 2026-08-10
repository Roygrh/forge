"""The MeridianERP tool contracts (FR-C4), plus the governed-rule lookup.

Eight tools, four reads, three writes, one retrieval:

===========================  ==========  ============================================
tool                         effect      what it is for
===========================  ==========  ============================================
``read_invoice``             read        the invoice as MeridianERP captured it
``get_vendor``               read        trust tier, history, bank account on file
``match_po``                 read        price matching against the purchase order
``get_receipts``             read        goods actually received against that PO
``query_rules``              read        the governed rules that apply, and why
``approve_invoice``          **write**   posts an approval — money moves after this
``schedule_payment``         **write**   schedules the payment itself
``request_info_from_vendor`` **write**   sends the vendor a question
===========================  ==========  ============================================

Every one of them is reached only through the tool gateway, which validates the
arguments against the schemas below, checks what the agent's DNA granted, and records
the attempt whether or not it ran (golden rule 2). The three writes are the sensitive
ones: an agent gets them at the autonomy its published definition declares, and a
``requires_approval`` grant parks the run instead of executing.

``query_rules`` is the one tool that is not an ERP call. It retrieves the governed rule
set — as data, with the facts each rule was evaluated against — so the agent reasons
over rules it *fetched* rather than rules someone compiled into it. Phase 4.3 replaces
it with authority-ranked knowledge retrieval over the same rule ids plus the policy
documents; the shape of what the agent receives is deliberately already close to that.
"""

from decimal import Decimal
from typing import Any

from app.erp.facts import build_fact_sheet
from app.erp.records import Invoice
from app.erp.store import ErpError, ErpStore
from app.rules.engine import evaluate
from app.rules.model import RuleSet
from app.tools.contract import ToolContract, ToolExecutionError, ToolInput

# --- Tool references ----------------------------------------------------------
# `slug@semver`, as a DNA document grants them. The docs/02-architecture/dna-examples
# definitions name exactly these.

READ_INVOICE_REF = "meridian-erp-read-invoice@1.0.0"
GET_VENDOR_REF = "meridian-erp-get-vendor@1.0.0"
MATCH_PO_REF = "meridian-erp-match-po@1.0.0"
GET_RECEIPTS_REF = "meridian-erp-get-receipts@1.0.0"
APPROVE_INVOICE_REF = "meridian-erp-approve-invoice@1.0.0"
REQUEST_INFO_REF = "meridian-erp-request-info-from-vendor@1.0.0"
SCHEDULE_PAYMENT_REF = "meridian-erp-schedule-payment@1.0.0"
QUERY_RULES_REF = "meridian-ap-rules-query@1.0.0"

#: The actor MeridianERP records for a write the runtime posted on its own authority.
ERP_ACTOR = "forge-runtime"


def _actor(call: ToolInput) -> str:
    """Who MeridianERP records as having posted this write.

    ``forge-runtime`` for an autonomous call, and the **approving human** for one that
    came out of the approval queue: the gateway injects the granted approval into the
    call's config, so the client's system of record names the person who released the
    action rather than the software that carried it out (FR-E4). An ERP entry that says
    "the AI did it" is exactly the answer Dana Whitfield said an auditor will not accept.
    """
    approval = call.config.get("approval")
    if isinstance(approval, dict) and approval.get("decided_by"):
        return str(approval["decided_by"])
    return ERP_ACTOR


# --- Shared schema fragments --------------------------------------------------

_INVOICE_ID: dict[str, Any] = {
    "type": "string",
    "description": "MeridianERP invoice id, e.g. inv-0001 (not the vendor's invoice number).",
}
#: Money crosses this boundary as an exact decimal string, never a JSON number — the
#: same convention the API contract uses, for the same reason.
_MONEY: dict[str, Any] = {"type": "string", "description": "Exact decimal amount in USD."}
_NULLABLE_MONEY: dict[str, Any] = {"type": ["string", "null"]}

_INVOICE_OUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "number", "vendor_id", "amount_usd", "status"],
    "properties": {
        "id": {"type": "string"},
        "number": {"type": "string"},
        "vendor_id": {"type": "string"},
        "po_number": {"type": ["string", "null"]},
        "amount_usd": _MONEY,
        "currency": {"type": "string"},
        "quantity_billed": {"type": ["integer", "null"]},
        "category": {"type": "string"},
        "payment_terms": {"type": "string"},
        "issue_date": {"type": "string"},
        "due_date": {"type": "string"},
        "received_date": {"type": "string"},
        "remit_to_bank_account_id": {"type": "string"},
        "status": {"type": "string"},
        "source_document": {"type": "string"},
    },
}

_VENDOR_OUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name", "trust_tier", "prior_invoice_count", "bank_account_id"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "trust_tier": {"enum": ["trusted", "standard", "new"]},
        "relationship_years": {"type": "string"},
        "prior_invoice_count": {"type": "integer"},
        "open_disputes": {"type": "integer"},
        "category": {"type": "string"},
        "bank_account_id": {"type": "string"},
        "phone_on_file": {
            "type": "string",
            "description": "The number to verify a bank change on — never one from the invoice.",
        },
    },
}


def _one_invoice_id(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["invoice_id"],
        "properties": {"invoice_id": {**_INVOICE_ID, "description": description}},
    }


def _invoice(erp: ErpStore, arguments: dict[str, Any]) -> Invoice:
    """Load the invoice a call names, translating a miss into a gateway refusal."""
    try:
        return erp.invoice(str(arguments["invoice_id"]))
    except ErpError as exc:
        raise ToolExecutionError(str(exc)) from exc


# --- Reads --------------------------------------------------------------------


def _read_invoice_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        return _invoice(erp, call.arguments).as_json()

    return ToolContract(
        ref=READ_INVOICE_REF,
        name="read_invoice",
        description=(
            "Read one invoice from MeridianERP exactly as it was captured, including the "
            "document it came from and the bank account it asks to be paid into."
        ),
        input_schema=_one_invoice_id("The invoice to read."),
        output_schema=_INVOICE_OUT,
        handler=handler,
    )


def _get_vendor_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        try:
            return erp.vendor(str(call.arguments["vendor_id"])).as_json()
        except ErpError as exc:
            raise ToolExecutionError(str(exc)) from exc

    return ToolContract(
        ref=GET_VENDOR_REF,
        name="get_vendor",
        description=(
            "Read a vendor master record: trust tier, length of relationship, prior "
            "invoice count, open disputes, and the bank account Meridian has on file."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["vendor_id"],
            "properties": {"vendor_id": {"type": "string", "description": "e.g. V-1001"}},
        },
        output_schema=_VENDOR_OUT,
        handler=handler,
    )


def _match_po_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        invoice = _invoice(erp, call.arguments)
        # Read from the same fact sheet the rules are evaluated against, so the numbers
        # the agent reasons about and the numbers a rule fires on cannot disagree.
        facts = build_fact_sheet(erp, invoice)
        return {
            "invoice_id": invoice.id,
            "po_number": invoice.po_number,
            "po_found": bool(facts["match.po_found"]),
            "po_total_usd": facts.get("match.po_total_usd"),
            "invoice_amount_usd": str(facts["invoice.amount_usd"]),
            "price_variance_usd": facts["match.price_variance_usd"],
            "price_variance_pct": facts["match.price_variance_pct"],
            "quantity_ordered": facts.get("match.quantity_ordered"),
            "quantity_billed": facts["match.quantity_billed"],
        }

    return ToolContract(
        ref=MATCH_PO_REF,
        name="match_po",
        description=(
            "Match an invoice against the purchase order it references and report the "
            "price variance in dollars and percent. Reports the numbers only — whether a "
            "variance is within tolerance is a rule, not a matching result."
        ),
        input_schema=_one_invoice_id("The invoice to match against its PO."),
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "po_found", "invoice_amount_usd"],
            "properties": {
                "invoice_id": {"type": "string"},
                "po_number": {"type": ["string", "null"]},
                "po_found": {"type": "boolean"},
                "po_total_usd": _NULLABLE_MONEY,
                "invoice_amount_usd": _MONEY,
                "price_variance_usd": _NULLABLE_MONEY,
                "price_variance_pct": {"type": ["string", "null"]},
                "quantity_ordered": {"type": ["integer", "null"]},
                "quantity_billed": {"type": ["integer", "null"]},
            },
        },
        handler=handler,
    )


def _get_receipts_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        po_number = str(call.arguments["po_number"])
        try:
            erp.purchase_order(po_number)
        except ErpError as exc:
            raise ToolExecutionError(str(exc)) from exc
        receipts = erp.receipts(po_number)
        return {
            "po_number": po_number,
            "receipts": [receipt.as_json() for receipt in receipts],
            "quantity_received_total": sum(receipt.quantity_received for receipt in receipts),
        }

    return ToolContract(
        ref=GET_RECEIPTS_REF,
        name="get_receipts",
        description=(
            "List the goods receipts posted against a purchase order — the third leg of "
            "the three-way match, and the evidence that anything actually arrived."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["po_number"],
            "properties": {"po_number": {"type": "string", "description": "e.g. PO-8801"}},
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["po_number", "receipts", "quantity_received_total"],
            "properties": {
                "po_number": {"type": "string"},
                "receipts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "po_number", "quantity_received", "received_on"],
                        "properties": {
                            "id": {"type": "string"},
                            "po_number": {"type": "string"},
                            "quantity_received": {"type": "integer"},
                            "received_on": {"type": "string"},
                        },
                    },
                },
                "quantity_received_total": {"type": "integer"},
            },
        },
        handler=handler,
    )


def _query_rules_tool(erp: ErpStore, rule_set: RuleSet) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        invoice = _invoice(erp, call.arguments)
        facts = build_fact_sheet(erp, invoice)
        matches = evaluate(rule_set, facts)
        return {
            "invoice_id": invoice.id,
            "ruleset_version": rule_set.version,
            "authority_level": "sme_validated",
            "facts": dict(facts),
            "applicable_rules": [match.model_dump() for match in matches],
            "governance_rules": [
                {"rule_id": rule.rule_id, "statement": rule.statement}
                for rule in rule_set.meta_rules
            ],
            "rules_evaluated": len(rule_set.rules),
        }

    return ToolContract(
        ref=QUERY_RULES_REF,
        name="query_rules",
        description=(
            "Retrieve the governed AP rules that apply to one invoice, with the facts "
            "each was evaluated against and the action it implies. Returns rules, not a "
            "decision: resolving conflicts (R-090), handling an empty result (R-091), and "
            "citing what was applied (R-092) are yours."
        ),
        input_schema=_one_invoice_id("The invoice to retrieve applicable rules for."),
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "ruleset_version", "facts", "applicable_rules"],
            "properties": {
                "invoice_id": {"type": "string"},
                "ruleset_version": {"type": "string"},
                "authority_level": {"type": "string"},
                "facts": {
                    "type": "object",
                    # A flat, dotted namespace whose keys are documented in
                    # app/erp/facts.py. Open by design: adding an observable fact must
                    # not require a schema migration in three places.
                    "additionalProperties": True,
                },
                "applicable_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["rule_id", "statement", "action", "citations", "because"],
                        "properties": {
                            "rule_id": {"type": "string"},
                            "statement": {"type": "string"},
                            "action": {
                                "type": ["string", "null"],
                                "description": "Null for a definition rule, which proposes none.",
                            },
                            "authority_level": {"type": "string"},
                            "citations": {"type": "array", "items": {"type": "string"}},
                            "because": {"type": "array", "items": {"type": "string"}},
                            "note": {"type": "string"},
                        },
                    },
                },
                "governance_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["rule_id", "statement"],
                        "properties": {
                            "rule_id": {"type": "string"},
                            "statement": {"type": "string"},
                        },
                    },
                },
                "rules_evaluated": {"type": "integer"},
            },
        },
        handler=handler,
    )


# --- Writes -------------------------------------------------------------------


def _approve_invoice_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        invoice = _invoice(erp, call.arguments)
        declared = Decimal(str(call.arguments["amount_usd"]))
        if declared != invoice.amount_usd:
            # The approval must be for the invoice as recorded. A mismatch means the
            # agent is approving a number it arrived at rather than the one on the
            # document, which is precisely what an approval must never be.
            raise ToolExecutionError(
                f"approval amount {declared} does not match invoice {invoice.number} "
                f"({invoice.amount_usd})"
            )

        # The per-agent ceiling its DNA declared. Governance stated in the definition and
        # enforced at the gateway boundary, not asserted in a prompt.
        cap = call.config.get("max_amount_usd")
        if cap is not None and invoice.amount_usd > Decimal(str(cap)):
            raise ToolExecutionError(
                f"invoice {invoice.number} is {invoice.amount_usd}, above the "
                f"max_amount_usd={cap} this agent version is granted; a human must approve"
            )

        try:
            posted = erp.approve_invoice(
                invoice.id,
                actor=_actor(call),
                detail={
                    "amount_usd": str(invoice.amount_usd),
                    "cited_rule_ids": list(call.arguments["cited_rule_ids"]),
                    "rationale": call.arguments.get("rationale", ""),
                },
            )
        except ErpError as exc:
            raise ToolExecutionError(str(exc)) from exc

        return {
            "invoice_id": invoice.id,
            "invoice_number": invoice.number,
            "approval_ref": posted.ref,
            "approved_amount_usd": str(invoice.amount_usd),
            "status": "approved",
        }

    return ToolContract(
        ref=APPROVE_INVOICE_REF,
        name="approve_invoice",
        description=(
            "Post an approval for an invoice in MeridianERP. Sensitive: this is the step "
            "after which money moves. Call it only when the decided action is "
            "auto_approve, and only for the amount the invoice actually states."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "amount_usd", "cited_rule_ids"],
            "properties": {
                "invoice_id": _INVOICE_ID,
                "amount_usd": {**_MONEY, "description": "Must equal the invoice's own amount."},
                "cited_rule_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "pattern": r"^R-\d{3}$"},
                    "description": "The rules that authorise this approval (R-092).",
                },
                "rationale": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "approval_ref", "status"],
            "properties": {
                "invoice_id": {"type": "string"},
                "invoice_number": {"type": "string"},
                "approval_ref": {"type": "string"},
                "approved_amount_usd": _MONEY,
                "status": {"type": "string"},
            },
        },
        # Declared per agent in its DNA grant, e.g. {"max_amount_usd": 10000}.
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_amount_usd": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Ceiling this agent version may approve without a human.",
                }
            },
        },
        handler=handler,
    )


def _schedule_payment_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        invoice = _invoice(erp, call.arguments)
        try:
            posted = erp.schedule_payment(
                invoice.id,
                actor=_actor(call),
                detail={
                    "pay_date": str(call.arguments["pay_date"]),
                    "amount_usd": str(invoice.amount_usd),
                },
            )
        except ErpError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return {
            "invoice_id": invoice.id,
            "payment_ref": posted.ref,
            "scheduled_for": str(call.arguments["pay_date"]),
            "amount_usd": str(invoice.amount_usd),
            "status": "scheduled",
        }

    return ToolContract(
        ref=SCHEDULE_PAYMENT_REF,
        name="schedule_payment",
        description=(
            "Schedule payment of an approved invoice. Sensitive: this moves money. "
            "Segregation of duties — the agent that validates an invoice is not the "
            "agent that pays it."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "pay_date"],
            "properties": {
                "invoice_id": _INVOICE_ID,
                "pay_date": {"type": "string", "description": "ISO date to pay on."},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "payment_ref", "status"],
            "properties": {
                "invoice_id": {"type": "string"},
                "payment_ref": {"type": "string"},
                "scheduled_for": {"type": "string"},
                "amount_usd": _MONEY,
                "status": {"type": "string"},
            },
        },
        handler=handler,
    )


def _request_info_tool(erp: ErpStore) -> ToolContract:
    def handler(call: ToolInput) -> dict[str, Any]:
        invoice = _invoice(erp, call.arguments)
        channel = str(call.arguments["channel"])
        try:
            posted = erp.request_info(
                invoice.id,
                actor=_actor(call),
                detail={"question": str(call.arguments["question"]), "channel": channel},
            )
        except ErpError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return {
            "invoice_id": invoice.id,
            "request_ref": posted.ref,
            "channel": channel,
            "status": "sent",
        }

    return ToolContract(
        ref=REQUEST_INFO_REF,
        name="request_info_from_vendor",
        description=(
            "Send the vendor a question about an invoice. Outbound contact on Meridian's "
            "behalf, so it is sensitive. Use phone_on_file — never a number taken from "
            "the invoice — whenever bank details are in question (R-042)."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "question", "channel"],
            "properties": {
                "invoice_id": _INVOICE_ID,
                "question": {"type": "string", "minLength": 1},
                "channel": {
                    "enum": ["email", "phone_on_file"],
                    "description": "phone_on_file dials the number in the vendor master.",
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["invoice_id", "request_ref", "status"],
            "properties": {
                "invoice_id": {"type": "string"},
                "request_ref": {"type": "string"},
                "channel": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        handler=handler,
    )


def meridian_tools(erp: ErpStore, rule_set: RuleSet) -> list[ToolContract]:
    """Build every AP tool over one ERP and one rule set.

    Bound at construction rather than looked up inside a handler: a gateway is built per
    request from the rules as they are *then* (``app.api.deps.get_tool_gateway``), which
    is what makes a rule edit take effect on the next run with nothing to invalidate.
    """
    return [
        _read_invoice_tool(erp),
        _get_vendor_tool(erp),
        _match_po_tool(erp),
        _get_receipts_tool(erp),
        _query_rules_tool(erp, rule_set),
        _approve_invoice_tool(erp),
        _request_info_tool(erp),
        _schedule_payment_tool(erp),
    ]
