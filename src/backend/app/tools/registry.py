"""The tool registry.

Tools are registered out of band and read-only through the API — an agent can be
*granted* a tool, never create one. Phase 3.2 registers exactly one: a trivial,
deterministic, side-effect-free lookup that exists to prove the path from model to
gateway to result and back. The MeridianERP tools arrive in Phase 4.2.
"""

from typing import Any

from app.tools.contract import ToolContract

GET_FACT_REF = "skeleton-get-fact@1.0.0"
GET_FACT_NAME = "get_fact"

#: The entire world this skeleton tool knows about. A dict, not a database: the point
#: is a deterministic round trip, not a knowledge layer (that is Phase 4.3).
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


def _get_fact(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the fact for a topic.

    Total by construction: the input schema's ``enum`` means the gateway has already
    rejected any topic that is not a key, so there is no "unknown topic" branch to get
    wrong. Pure, deterministic, no I/O.
    """
    topic = str(arguments["topic"])
    return {"topic": topic, "fact": _FACTS[topic]}


GET_FACT = ToolContract(
    ref=GET_FACT_REF,
    name=GET_FACT_NAME,
    description="Look up a single governed fact about the Forge platform by topic.",
    input_schema=GET_FACT_INPUT_SCHEMA,
    output_schema=GET_FACT_OUTPUT_SCHEMA,
    handler=_get_fact,
)


class ToolRegistry:
    """The catalogue of tools the gateway is able to run.

    Lookup is by both ``ref`` (what a DNA grant names) and ``name`` (what a model
    calls); a miss on either returns ``None`` so the gateway can fail closed rather
    than improvise.
    """

    def __init__(self, tools: list[ToolContract] | None = None) -> None:
        self._tools = list(tools if tools is not None else [GET_FACT])

    def by_name(self, name: str) -> ToolContract | None:
        """Return the tool a model called, or ``None`` if no such tool is registered."""
        return next((tool for tool in self._tools if tool.name == name), None)

    def by_ref(self, ref: str) -> ToolContract | None:
        """Return the tool a DNA document granted, or ``None``."""
        return next((tool for tool in self._tools if tool.ref == ref), None)

    def all(self) -> list[ToolContract]:
        """Every registered tool, for the read-only catalogue endpoint."""
        return list(self._tools)
