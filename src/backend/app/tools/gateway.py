"""The tool gateway: the single, mandatory path from an agent to any tool.

**This module is the one enforcement point.** ``ToolContract.handler`` is invoked in
exactly one place in the codebase — :meth:`ToolGateway._execute` — so "no tool call
bypasses the gateway" is a property of the call graph rather than a rule people
remember. ``tests/test_governance.py`` reads the source tree and fails if a second call
site ever appears.

Every invocation is checked in a fixed order, and the *first* check that fails ends it:

===  ===============================  ======================  =====================
 #   check                            on failure              reason code
===  ===============================  ======================  =====================
 1   is the tool **registered**?       blocked                 ``tool_unknown``
 2   does this DNA **grant** it?       blocked                 ``permission_denied``
 3   is the grant ``forbidden``?       denied                  ``permission_denied``
 4   is the grant's **config** valid?  blocked                 ``tool_config_invalid``
 5   do the **arguments** validate?    blocked                 ``args_invalid``
 6   ``requires_approval`` and no       validated, parked       ``approval_required``
     recorded release?
 7   did the tool accept the call?     blocked                 ``tool_failed``
===  ===============================  ======================  =====================

Only a call that survives all seven executes. Nothing here is best-effort: an unknown
tool, a missing grant, or bad arguments produces a recorded refusal with a machine-
readable reason, never a guess (FR-C5, golden rule 3).

Note the ordering. Permission is checked before arguments, so a call to a tool the agent
was never granted is refused as *ungranted* rather than critiqued for its arguments —
except for ``requires_approval``, which comes last precisely because a human must never
be asked to approve a call that would have been rejected as malformed anyway.

Step 6 is where the human-in-the-loop queue meets the enforcement point. A parked call
is released by an :class:`~app.tools.contract.ApprovalRelease` — the approval row a
person granted — and by nothing else: there is no "skip approval" flag, no privileged
caller, and no code path that reaches :meth:`ToolGateway._execute` around this check.
Every other check still applies to a released call, so an approval granted yesterday
cannot run a tool a new version has since forbidden.

The gateway does not touch the database. It returns a :class:`ToolOutcome` for every
attempt, and the runtime's recorder persists all of them — permitted, parked, or refused
— which is how "record every invocation" stays true without wiring a session through
here.
"""

import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError

from app.dna.model import Autonomy, Dna, ToolGrant
from app.governance import GovernanceReason
from app.tools.contract import (
    ApprovalRelease,
    ToolContract,
    ToolExecutionError,
    ToolInput,
    ToolOutcome,
)
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: The three autonomy levels, and what the gateway does with each. Exhaustive by
#: construction: :meth:`ToolGateway.invoke` dispatches on this mapping, so a level added
#: to the DNA schema without a decision here fails loudly instead of defaulting to
#: "execute". Fail-closed applies to the platform's own gaps too.
AUTONOMY_EFFECT: dict[Autonomy, str] = {
    "forbidden": "deny",
    "requires_approval": "park",
    "autonomous": "execute",
}


class ToolGateway:
    """Validates, authorises, and executes tool calls."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry if registry is not None else ToolRegistry()

    @property
    def registry(self) -> ToolRegistry:
        """The catalogue this gateway runs over."""
        return self._registry

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

    def invoke(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        dna: Dna,
        release: ApprovalRelease | None = None,
    ) -> ToolOutcome:
        """Run a tool call, or refuse it. Never raises for a policy or input failure.

        ``release`` is the recorded human approval for *this* call, supplied only by the
        approval queue when it resumes a parked run. Without one, a ``requires_approval``
        grant parks. With one, the call runs — after every other check has passed again.
        """
        tool = self._registry.by_name(name)
        if tool is None:
            return ToolOutcome(
                tool_name=name,
                tool_ref=name,
                autonomy=None,
                arguments=arguments,
                status="blocked",
                error=f"unknown tool {name!r}: not in the gateway registry",
                reason=GovernanceReason.TOOL_UNKNOWN,
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
                reason=GovernanceReason.PERMISSION_DENIED,
            )

        effect = AUTONOMY_EFFECT.get(grant.autonomy)
        if effect is None:  # pragma: no cover - unreachable while the DNA schema holds
            # An autonomy level the gateway has no decision for is refused, never run.
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.PERMISSION_DENIED,
                f"autonomy level {grant.autonomy!r} has no enforcement rule in this build",
            )

        if effect == "deny":
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="denied",
                error=f"tool {tool.ref!r} is explicitly forbidden by this agent version",
                reason=GovernanceReason.PERMISSION_DENIED,
            )

        config = dict(grant.config or {})
        config_error = _check_config(tool, config)
        if config_error is not None:
            # A definition the gateway cannot honour is refused rather than executed
            # with the configuration ignored — which would run an agent with weaker
            # limits than the one that was published.
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.TOOL_CONFIG_INVALID,
                f"invalid config for {tool.ref!r} in this agent version: {config_error}",
            )

        if tool.knowledge_scoped:
            # Injected *after* config validation, from the published DNA and never from
            # the model's arguments: the collections a retrieval may read are part of
            # the definition that was reviewed and published, so the gateway — the one
            # enforcement point — is where that scope is applied (FR-C3, FR-D2).
            config["knowledge_scope"] = {
                "tenant_slug": dna.identity.tenant_id,
                "collections": list(dna.knowledge.collections),
                "authority_policy": dna.knowledge.authority_policy,
            }

        schema_error = _validate(tool.input_schema, arguments)
        if schema_error is not None:
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.ARGS_INVALID,
                f"invalid arguments for {tool.name!r}: {schema_error}",
            )

        if effect == "park" and release is None:
            # Validated, permitted in form, and deliberately not run. The run stops in
            # `awaiting_approval` and the approval queue takes over (FR-E1..E4). The
            # honest state is "waiting", never "done", and it stays waiting until a
            # person decides — an approval nobody grants expires into a cancellation.
            return ToolOutcome(
                tool_name=tool.name,
                tool_ref=tool.ref,
                autonomy=grant.autonomy,
                arguments=arguments,
                status="validated",
                reason=GovernanceReason.APPROVAL_REQUIRED,
            )

        if release is not None:
            # Injected after config validation, exactly as `knowledge_scope` is: the
            # approver's identity is not something a DNA grant declares, and a tool that
            # writes to a system of record posts it under the human who released the
            # action rather than under the runtime (FR-E4).
            config["approval"] = release.as_json()

        return self._execute(tool, grant, arguments, config, release)

    def _execute(
        self,
        tool: ToolContract,
        grant: ToolGrant,
        arguments: dict[str, Any],
        config: dict[str, Any],
        release: ApprovalRelease | None = None,
    ) -> ToolOutcome:
        """Run the handler. **The only place in Forge that calls a tool handler.**"""
        try:
            result = tool.handler(ToolInput(arguments=arguments, config=config))
        except ToolExecutionError as exc:
            # An anticipated refusal from the tool itself (unknown record, wrong state).
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.TOOL_FAILED,
                f"tool {tool.name!r} refused the call: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
            logger.exception("tool %s raised", tool.ref)
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.TOOL_FAILED,
                f"tool {tool.name!r} failed: {exc}",
            )

        # The output contract is checked too: a tool that returns something its own
        # schema forbids is a broken tool, and its result must not reach the model.
        output_error = _validate(tool.output_schema, result)
        if output_error is not None:
            return self._refuse(
                tool,
                grant,
                arguments,
                GovernanceReason.TOOL_FAILED,
                f"tool {tool.name!r} returned a result violating its schema: {output_error}",
            )

        return ToolOutcome(
            tool_name=tool.name,
            tool_ref=tool.ref,
            autonomy=grant.autonomy,
            arguments=arguments,
            status="executed",
            result=result,
            release=release,
        )

    @staticmethod
    def _refuse(
        tool: ToolContract,
        grant: ToolGrant,
        arguments: dict[str, Any],
        reason: GovernanceReason,
        error: str,
    ) -> ToolOutcome:
        """A recorded refusal of a granted tool, with the code that explains it."""
        return ToolOutcome(
            tool_name=tool.name,
            tool_ref=tool.ref,
            autonomy=grant.autonomy,
            arguments=arguments,
            status="blocked",
            error=error,
            reason=reason,
        )


def _check_config(tool: ToolContract, config: dict[str, Any]) -> str | None:
    """Validate a grant's ``config`` against the tool's own config schema."""
    if tool.config_schema is None:
        return None if not config else "this tool takes no configuration"
    return _validate(tool.config_schema, config)


def _validate(schema: dict[str, Any], instance: object) -> str | None:
    """Return the first schema violation as a message, or ``None`` if valid."""
    try:
        Draft202012Validator(schema).validate(instance)
    except JsonSchemaValidationError as exc:
        path = "/".join(str(part) for part in exc.absolute_path)
        return f"{path or '<root>'}: {exc.message}"
    return None
