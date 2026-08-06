"""The deterministic stand-in the seeded AP agents run on.

:class:`~app.llm.adapters.fake.FakeAdapter` replays a script a *test* wrote. This one has
no script: it derives each turn from the conversation so far, so a freshly seeded,
freshly started stack answers ``POST /api/v1/runs`` correctly with no key, no network,
and no test harness. That is what makes the demo demonstrable rather than merely tested,
and what lets an evaluator watch a real invoice reach a rule-cited decision on a laptop.

**It stands in for the model, not for the platform.** It plans (which tool next) and it
reasons (which of the retrieved rules wins, and what to cite) — the two things a real
model would do. It contains no business rules: it cannot say what R-020 means, only what
the ``query_rules`` tool result told it. Swap ``"provider": "fake"`` for
``"provider": "anthropic"`` in a DNA document and a real model does the same job from the
same tool results and the same prompt; nothing else changes (ADR-005).

Three plans, chosen by what the agent's DNA granted:

* ``query_rules`` granted            -> **validate**: read, contextualise, retrieve rules,
                                        resolve them (R-090/R-091), approve if entitled.
* ``request_info_from_vendor`` only  -> **communicate**: draft the vendor question.
* otherwise                          -> **intake**: read and normalise.
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.actions import most_restrictive
from app.llm.adapters.base import LlmAdapter
from app.llm.contract import CompletionResult, Message, ModelSpec, ToolCall, ToolSpec, Usage

#: The fail-closed default the agent cites when nothing it retrieved applies (R-091).
NO_RULE_MATCH_RULE = "R-091"

#: Cited when several rules fired with different actions and one had to win (R-090).
CONFLICT_RULE = "R-090"

#: Nominal usage, so budgets and cost totals are exercised rather than reported as zero.
_USAGE = Usage(input_tokens=200, output_tokens=100, cost_usd=Decimal("0.0005"))

#: The invoice fields intake normalises out of the raw ERP record.
_NORMALISED_FIELDS = (
    "id",
    "number",
    "vendor_id",
    "po_number",
    "amount_usd",
    "currency",
    "category",
    "payment_terms",
    "issue_date",
    "due_date",
    "remit_to_bank_account_id",
)


class MeridianDemoAdapter(LlmAdapter):
    """Answers an AP agent's turns, derived from the conversation."""

    provider = "fake"

    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
    ) -> CompletionResult:
        """Produce the next turn: one tool call, or the final decision."""
        granted = {tool.name for tool in tools}
        results = _tool_results(messages)
        run_input = _run_input(messages)

        if "query_rules" in granted:
            turn = _validate_plan(granted, results, run_input)
        elif "request_info_from_vendor" in granted:
            turn = _communicate_plan(results, run_input)
        else:
            turn = _intake_plan(granted, results, run_input)

        content, tool_call = turn
        return CompletionResult(
            provider=self.provider,
            model_id=model.model_id,
            content=content,
            tool_call=tool_call,
            usage=_USAGE,
        )


#: One turn: either free-text content (a decision) or a tool call, never both.
Turn = tuple[str | None, ToolCall | None]


def _call(name: str, **arguments: object) -> Turn:
    return None, ToolCall(name=name, arguments=arguments)


def _decide(
    action: str, citations: list[str], reasoning: str, output: dict[str, Any] | None = None
) -> Turn:
    payload: dict[str, Any] = {
        "action": action,
        "citations": citations,
        "reasoning": reasoning,
    }
    if output is not None:
        payload["output"] = output
    return json.dumps(payload), None


# --- The validation plan ------------------------------------------------------


def _validate_plan(
    granted: set[str], results: dict[str, dict[str, Any]], run_input: dict[str, Any]
) -> Turn:
    """Gather evidence, retrieve the rules, then decide from what came back."""
    invoice_id = str(run_input.get("invoice_id", ""))
    invoice = results.get("read_invoice")

    if "read_invoice" in granted and invoice is None:
        return _call("read_invoice", invoice_id=invoice_id)
    if invoice is None:
        # No way to establish what is being validated. Fail closed rather than reason
        # about an invoice the agent never read.
        return _decide(
            "escalate",
            [NO_RULE_MATCH_RULE],
            "The invoice could not be read, so no rule could be evaluated against it.",
        )

    if "get_vendor" in granted and "get_vendor" not in results:
        return _call("get_vendor", vendor_id=str(invoice["vendor_id"]))

    po_number = invoice.get("po_number")
    if po_number is not None:
        if "match_po" in granted and "match_po" not in results:
            return _call("match_po", invoice_id=invoice_id)
        if "get_receipts" in granted and "get_receipts" not in results:
            return _call("get_receipts", po_number=str(po_number))

    rules = results.get("query_rules")
    if rules is None:
        return _call("query_rules", invoice_id=invoice_id)

    action, citations, reasoning = _resolve(rules)

    # Only an auto_approve entitles the agent to post an approval — and it posts it
    # before deciding, so the decision records an approval that actually happened.
    entitled = action == "auto_approve" and "approve_invoice" in granted
    if entitled and "approve_invoice" not in results:
        return _call(
            "approve_invoice",
            invoice_id=invoice_id,
            amount_usd=str(invoice["amount_usd"]),
            cited_rule_ids=citations,
            rationale=reasoning,
        )

    return _decide(action, citations, reasoning)


def _resolve(rules: dict[str, Any]) -> tuple[str, list[str], str]:
    """Turn a ``query_rules`` result into an action, the citations, and the reasoning.

    This is the reasoning a real model performs over the same payload: apply the most
    restrictive action among the rules that fired (R-090), escalate when none did
    (R-091), and cite everything applied (R-092).
    """
    applicable: list[dict[str, Any]] = list(rules.get("applicable_rules", []))
    proposed = [str(rule["action"]) for rule in applicable if rule.get("action")]
    action = most_restrictive(proposed)

    if action is None:
        matched = ", ".join(str(rule["rule_id"]) for rule in applicable) or "none"
        return (
            "escalate",
            [NO_RULE_MATCH_RULE],
            "No rule in the governed set proposes an action for this invoice "
            f"(rules matched: {matched}; {rules.get('rules_evaluated', 0)} evaluated at "
            f"ruleset {rules.get('ruleset_version')}). Escalating rather than guessing.",
        )

    citations: list[str] = []
    for rule in applicable:
        for cited in rule.get("citations", []):
            if cited not in citations:
                citations.append(str(cited))

    conflicted = len(set(proposed)) > 1
    if conflicted:
        # The conflict itself was resolved by a rule, so that rule is cited too.
        citations.append(CONFLICT_RULE)

    deciding = [
        str(rule["rule_id"]) for rule in applicable if str(rule.get("action") or "") == action
    ]
    evidence = "; ".join(
        f"{rule['rule_id']} ({', '.join(rule.get('because', [])) or 'no conditions'})"
        for rule in applicable
    )
    reasoning = (
        f"Applied the governed AP rule set v{rules.get('ruleset_version')}. "
        f"Rules that fired: {evidence}. "
        f"{', '.join(deciding)} decides {action}"
    )
    if conflicted:
        reasoning += (
            f", which is the most restrictive of the actions proposed "
            f"({', '.join(sorted(set(proposed)))}) under R-090"
        )
    return action, citations, reasoning + "."


# --- The intake and communication plans ---------------------------------------


def _intake_plan(
    granted: set[str], results: dict[str, dict[str, Any]], run_input: dict[str, Any]
) -> Turn:
    """Read the invoice and hand the normalised fields on."""
    invoice = results.get("read_invoice")
    if "read_invoice" in granted and invoice is None:
        return _call("read_invoice", invoice_id=str(run_input.get("invoice_id", "")))

    if invoice is None:
        return _decide(
            "escalate",
            [NO_RULE_MATCH_RULE],
            "The invoice could not be read, so there is nothing to normalise.",
        )

    normalised = {field: invoice.get(field) for field in _NORMALISED_FIELDS}
    missing = [
        field for field, value in normalised.items() if value is None and field != "po_number"
    ]
    if missing:
        return _decide(
            "escalate",
            [NO_RULE_MATCH_RULE],
            f"Required fields are missing from the captured document: {', '.join(missing)}. "
            "Escalating rather than inferring them.",
            output={"normalised_invoice": normalised, "missing_fields": missing},
        )

    return _decide(
        "auto_approve",
        [NO_RULE_MATCH_RULE],
        f"Invoice {invoice['number']} from vendor {invoice['vendor_id']} normalised from "
        f"{invoice.get('source_document')} with every required field present. R-091 was "
        "evaluated and did not fire: nothing was ambiguous, so the invoice is admitted "
        "for validation rather than escalated.",
        output={"normalised_invoice": normalised, "missing_fields": []},
    )


def _communicate_plan(results: dict[str, dict[str, Any]], run_input: dict[str, Any]) -> Turn:
    """Draft one question to the vendor and send it — through the approval queue."""
    sent = results.get("request_info_from_vendor")
    if sent is None:
        question = str(
            run_input.get("question")
            or "Could you confirm the purchase order and remit-to details for this invoice?"
        )
        return _call(
            "request_info_from_vendor",
            invoice_id=str(run_input.get("invoice_id", "")),
            question=question,
            # The number on file, never one from the invoice (R-042).
            channel=str(run_input.get("channel", "phone_on_file")),
        )

    return _decide(
        "escalate",
        [NO_RULE_MATCH_RULE],
        f"Information request {sent.get('request_ref')} sent to the vendor; the invoice "
        "waits on their reply and is left for a human to pick up.",
    )


# --- Reading the conversation -------------------------------------------------


def _messages_as_json(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Every user turn that carries a JSON object, oldest first."""
    payloads = []
    for message in messages:
        if message.role != "user":
            continue
        # The runtime writes tool results as JSON and the run input after a text label;
        # take whatever parses and ignore the rest.
        _, _, tail = message.content.partition("\n")
        for candidate in (message.content, tail):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
                break
    return payloads


def _tool_results(messages: Sequence[Message]) -> dict[str, dict[str, Any]]:
    """Every tool result in the transcript, keyed by tool name (latest wins)."""
    results: dict[str, dict[str, Any]] = {}
    for payload in _messages_as_json(messages):
        observed = payload.get("tool_result")
        if isinstance(observed, dict) and isinstance(observed.get("result"), dict):
            results[str(observed["name"])] = observed["result"]
    return results


def _run_input(messages: Sequence[Message]) -> dict[str, Any]:
    """The trigger payload the run started with."""
    for payload in _messages_as_json(messages):
        if "tool_result" not in payload:
            return payload
    return {}
