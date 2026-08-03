"""The tool gateway: the single, mandatory path from an agent to any tool.

Every invocation is checked in a fixed order, and the *first* check that fails ends it:

1. Is the tool **registered**?            unknown tool  -> blocked
2. Does this agent's DNA **grant** it?    no grant      -> blocked
3. What **autonomy** did the DNA declare? forbidden     -> denied
4. Do the **arguments** satisfy its input schema? no    -> blocked

Only a call that survives all four executes. Nothing here is best-effort: an unknown
tool, a missing grant, or bad arguments produces a recorded refusal, never a guess
(FR-C5, golden rule 3). Note the ordering — permission is checked before arguments, so
a call to a tool the agent was never granted is refused as *ungranted*, not critiqued
for its arguments.

The gateway does not touch the database. It returns a :class:`ToolOutcome` for every
attempt, and the runtime's recorder persists all of them — permitted or refused — which
is how "record every invocation" stays true without wiring a session through here.
"""

import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError

from app.dna.model import Dna
from app.tools.contract import ToolContract, ToolOutcome
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolGateway:
    """Validates, authorises, and executes tool calls."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry if registry is not None else ToolRegistry()

    def granted_tools(self, dna: Dna) -> list[ToolContract]:
        """Return the tools this DNA actually exposes to the model.

        ``forbidden`` grants are excluded: the definition recorded that the tool was
        considered and refused, and the model is never shown a door it may not open.
        A grant naming an unregistered tool is skipped here and would be refused at
        call time anyway.
        """
        granted = []
        for grant in dna.tools:
            if grant.autonomy == "forbidden":
                continue
            tool = self._registry.by_ref(grant.ref)
            if tool is None:
                logger.warning("DNA grants unregistered tool %s; ignoring", grant.ref)
                continue
            granted.append(tool)
        return granted

    def invoke(self, *, name: str, arguments: dict[str, Any], dna: Dna) -> ToolOutcome:
        """Run a tool call, or refuse it. Never raises for a policy or input failure."""
        tool = self._registry.by_name(name)
        if tool is None:
            return ToolOutcome(
                tool_name=name,
                tool_ref=name,
                autonomy=None,
                arguments=arguments,
                status="blocked",
                error=f"unknown tool {name!r}: not in the gateway registry",
            )

        grant = dna.grant_for(tool.ref)
        if grant is None:
            # Least privilege: a tool absent from the DNA does not exist for this agent.
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=None,
                arguments=arguments,
                status="blocked",
                error=f"tool {tool.ref!r} is not granted to this agent version",
            )

        if grant.autonomy == "forbidden":
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="denied",
                error=f"tool {tool.ref!r} is explicitly forbidden by this agent version",
            )

        if grant.autonomy == "requires_approval":
            # Phase 3.x turns this into an approval-queue entry and pauses the run.
            # Until the approval service exists, the honest answer is to refuse: an
            # approval the platform cannot obtain must never become an execution.
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="blocked",
                error=(
                    f"tool {tool.ref!r} requires human approval; the approval service "
                    "is not available in this phase"
                ),
            )

        schema_error = _validate(tool.input_schema, arguments)
        if schema_error is not None:
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="blocked",
                error=f"invalid arguments for {tool.name!r}: {schema_error}",
            )

        try:
            result = tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
            logger.exception("tool %s raised", tool.ref)
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="blocked",
                error=f"tool {tool.name!r} failed: {exc}",
            )

        # The output contract is checked too: a tool that returns something its own
        # schema forbids is a broken tool, and its result must not reach the model.
        output_error = _validate(tool.output_schema, result)
        if output_error is not None:
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="blocked",
                error=f"tool {tool.name!r} returned a result violating its schema: {output_error}",
            )

        return ToolOutcome(
            tool_name=tool.name,
            tool_ref=tool.ref,
            autonomy=grant.autonomy,
            arguments=arguments,
            status="executed",
            result=result,
        )


def _validate(schema: dict[str, Any], instance: object) -> str | None:
    """Return the first schema violation as a message, or ``None`` if valid."""
    try:
        Draft202012Validator(schema).validate(instance)
    except JsonSchemaValidationError as exc:
        path = "/".join(str(part) for part in exc.absolute_path)
        return f"{path or '<root>'}: {exc.message}"
    return None
