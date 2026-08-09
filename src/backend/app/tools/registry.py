"""The tool registry.

Tools are registered out of band and read-only through the API — an agent can be
*granted* a tool, never create one. The catalogue is the eight MeridianERP and
rule-lookup tools of :mod:`app.tools.meridian` (FR-C4), the governed knowledge
retrieval of :mod:`app.tools.knowledge` (FR-D2..D4), plus one trivial fact lookup
that belongs to the platform rather than to the domain and exists so the runtime can be
exercised without any business data at all.
"""

from typing import Any

from app.erp.store import ErpStore, get_erp
from app.rules.catalog import catalog_rule_set
from app.rules.model import RuleSet
from app.tools.contract import ToolContract, ToolInput
from app.tools.knowledge import SEARCH_KNOWLEDGE
from app.tools.meridian import meridian_tools

GET_FACT_REF = "skeleton-get-fact@1.0.0"
GET_FACT_NAME = "get_fact"

#: The entire world this tool knows about. A dict, not a database: it exists to prove a
#: deterministic round trip from model to gateway and back, with no domain attached —
#: which is what makes it useful as the runtime's own regression fixture.
_FACTS: dict[str, str] = {
    "forge": "Forge executes business agents from declarative, versioned DNA documents.",
    "governance": "Least privilege, HITL approvals, eval-gated publishing, full traceability.",
    "meridian": "Meridian Supply Co. is the simulated accounts-payable client.",
}

GET_FACT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic"],
    "properties": {
        "topic": {
            "type": "string",
            "enum": sorted(_FACTS),
            "description": "Which fact to look up.",
        }
    },
}

GET_FACT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic", "fact"],
    "properties": {
        "topic": {"type": "string"},
        "fact": {"type": "string"},
    },
}


def _get_fact(call: ToolInput) -> dict[str, Any]:
    """Return the fact for a topic.

    Total by construction: the input schema's ``enum`` means the gateway has already
    rejected any topic that is not a key, so there is no "unknown topic" branch to get
    wrong. Pure, deterministic, no I/O.
    """
    topic = str(call.arguments["topic"])
    return {"topic": topic, "fact": _FACTS[topic]}


GET_FACT = ToolContract(
    ref=GET_FACT_REF,
    name=GET_FACT_NAME,
    description="Look up a single governed fact about the Forge platform by topic.",
    input_schema=GET_FACT_INPUT_SCHEMA,
    output_schema=GET_FACT_OUTPUT_SCHEMA,
    handler=_get_fact,
)


def build_tools(erp: ErpStore | None = None, rule_set: RuleSet | None = None) -> list[ToolContract]:
    """Every registered tool, bound to one ERP and one rule set.

    Defaults exist for scripts and unit tests: the process-wide simulated ERP, and the
    rule catalogue as shipped. The API never relies on them — ``app.api.deps`` loads the
    rules from the database per request, which is what makes an edited rule take effect
    without a redeploy.
    """
    return [
        GET_FACT,
        *meridian_tools(erp or get_erp(), rule_set or catalog_rule_set()),
        # Not bound to anything here: retrieval owns its own session, and its scope
        # arrives per call from the DNA via the gateway (knowledge_scoped).
        SEARCH_KNOWLEDGE,
    ]


class ToolRegistry:
    """The catalogue of tools the gateway is able to run.

    Lookup is by both ``ref`` (what a DNA grant names) and ``name`` (what a model
    calls); a miss on either returns ``None`` so the gateway can fail closed rather
    than improvise.
    """

    def __init__(self, tools: list[ToolContract] | None = None) -> None:
        self._tools = list(tools if tools is not None else build_tools())

    def by_name(self, name: str) -> ToolContract | None:
        """Return the tool a model called, or ``None`` if no such tool is registered."""
        return next((tool for tool in self._tools if tool.name == name), None)

    def by_ref(self, ref: str) -> ToolContract | None:
        """Return the tool a DNA document granted, or ``None``."""
        return next((tool for tool in self._tools if tool.ref == ref), None)

    def all(self) -> list[ToolContract]:
        """Every registered tool, for the read-only catalogue endpoint."""
        return list(self._tools)
