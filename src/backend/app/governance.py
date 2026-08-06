"""The platform's governance vocabulary: why it stops, and who may do what.

Two things live here, and they are here rather than scattered because both must read
the *same* way in the runtime, in the audit log, in the API, and on the screen:

* :class:`GovernanceReason` — every way Forge refuses to continue, as a machine-readable
  code with a human-readable explanation beside it. A run that stopped always says why,
  in the same words, wherever you look at it.
* :class:`Role` / :class:`Permission` — who may configure agents and who may approve
  their actions, and the structural guarantee that those are never the same person
  (NFR-5).

The module imports nothing from the rest of the application on purpose: the runtime, the
tool gateway, the trace, and the API layer all depend on this vocabulary and on each
other in various directions, and a dependency-free definition is what lets them share it.
"""

from enum import StrEnum


class GovernanceReason(StrEnum):
    """Why the platform stopped, blocked, or refused.

    Every fail-closed path in Forge ends in exactly one of these. They are grouped by
    where the stop originates — the tool gateway, the decision contract, a hard limit,
    or the platform itself — and the grouping is the map of everything that can refuse.
    """

    # --- Tool gateway denials (FR-C1, FR-C5) ---------------------------------

    TOOL_UNKNOWN = "tool_unknown"
    """The model asked for a tool that is not in the registry. No guessing at what it
    might have meant: an unknown tool is refused, recorded, and the run stops."""

    PERMISSION_DENIED = "permission_denied"
    """The agent's DNA does not grant this tool, or grants it as ``forbidden``. Least
    privilege is the shape of the definition, and the gateway enforces it (FR-C3)."""

    ARGS_INVALID = "args_invalid"
    """The call did not satisfy the tool's declared input schema. Validation happens
    before the handler runs, so a malformed call never reaches a system of record."""

    TOOL_CONFIG_INVALID = "tool_config_invalid"
    """The DNA attached configuration the tool cannot honour (an unknown key, a bad
    ceiling). Refused rather than executed with the configuration ignored — which would
    run an agent under weaker limits than the one that was published."""

    TOOL_FAILED = "tool_failed"
    """The tool itself refused the call or failed: an unknown record, a state it will
    not accept, or an unexpected error. Its answer is recorded, not interpreted."""

    APPROVAL_REQUIRED = "approval_required"
    """The DNA grants this tool only ``requires_approval``. The call was validated and
    **parked**: the run stops in ``awaiting_approval`` and nothing was executed. An
    approval the platform cannot obtain never decays into an execution (FR-E2, FR-E3)."""

    # --- Decision contract (ADR-006, R-091) ----------------------------------

    NO_RULE_MATCH = "no_rule_match"
    """No governed rule applied to this case, so the agent escalated under R-091 — the
    fail-closed default. Absence of a rule is never licence to improvise."""

    LOW_CONFIDENCE = "low_confidence"
    """The decision's stated confidence was below the floor its DNA declares. The action
    is overridden to an escalation whatever the agent proposed (R-091)."""

    INVALID_OUTPUT = "invalid_output"
    """Model output failed the response schema twice — once, then once after correction
    (ADR-006). Malformed output never becomes an action."""

    # --- Hard limits from the DNA (FR-B3, NFR-3) -----------------------------

    STEP_LIMIT = "step_limit"
    """The loop reached ``guardrails.max_steps`` without reaching a decision."""

    TIMEOUT = "timeout"
    """The run passed ``guardrails.timeout_seconds`` of wall clock."""

    BUDGET_EXCEEDED = "budget_exceeded"
    """The run reached the token or cost ceiling in its DNA ``model`` block."""

    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"
    """This agent has already spent ``model.max_cost_usd_per_day`` today across all its
    runs. Further runs are refused until the day rolls over — the ceiling is on the
    agent, so one runaway definition cannot be worked around by starting more runs."""

    # --- Platform ------------------------------------------------------------

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """The DNA names a provider or model the gateway cannot serve or meter."""

    UNSUPPORTED_DEFINITION = "unsupported_definition"
    """The DNA is valid but declares a capability this build cannot honour — knowledge
    collections before the knowledge layer exists, say. Running it anyway would silently
    execute a *different*, less-informed agent than the one that was published."""

    # --- Not a denial --------------------------------------------------------

    AGENT_DECISION = "agent_decision"
    """The agent reached a decision whose action is a human queue (``escalate`` /
    ``block_escalate``). The loop worked; the answer is 'a person'. Recorded as a reason
    so a terminal state always has one, but it is not a block."""


#: Plain-language explanation per reason, written for someone who has never read the
#: code. The trace serves these to the API and the SPA renders them verbatim, so the
#: sentence a compliance officer reads is the same sentence the platform acted on.
REASON_EXPLANATION: dict[GovernanceReason, str] = {
    GovernanceReason.TOOL_UNKNOWN: (
        "The agent asked for a tool that does not exist. The platform refused rather "
        "than guessing what was meant, and nothing was executed."
    ),
    GovernanceReason.PERMISSION_DENIED: (
        "The agent asked for a tool its own definition does not permit it to use. "
        "Least privilege is part of the published definition, so the call was refused "
        "and nothing was executed."
    ),
    GovernanceReason.ARGS_INVALID: (
        "The call did not match the tool's declared inputs. It was rejected before the "
        "tool ran, so no system of record was touched."
    ),
    GovernanceReason.TOOL_CONFIG_INVALID: (
        "This agent's definition configures the tool in a way the tool cannot honour. "
        "The platform refused rather than running with the configuration ignored."
    ),
    GovernanceReason.TOOL_FAILED: (
        "The target system refused the call — an unknown record, or a state it will not "
        "accept. The refusal was recorded as given, not interpreted."
    ),
    GovernanceReason.APPROVAL_REQUIRED: (
        "This action requires a person. The call was checked and held for approval; it "
        "was not carried out, and it never will be without someone releasing it."
    ),
    GovernanceReason.NO_RULE_MATCH: (
        "No governed rule covered this case, so it went to a human. The platform never "
        "improvises when the rulebook is silent."
    ),
    GovernanceReason.LOW_CONFIDENCE: (
        "The agent was not confident enough in its own answer, so the platform "
        "overrode it and escalated to a human."
    ),
    GovernanceReason.INVALID_OUTPUT: (
        "The agent's answer did not fit the required format, twice. A malformed answer "
        "is never turned into an action."
    ),
    GovernanceReason.STEP_LIMIT: (
        "The agent used up the number of steps its definition allows without reaching a "
        "decision, so the run was stopped."
    ),
    GovernanceReason.TIMEOUT: (
        "The run took longer than its definition allows and was stopped. A run that "
        "overruns is escalated, never silently completed."
    ),
    GovernanceReason.BUDGET_EXCEEDED: (
        "The run reached the spending or token ceiling its definition sets, and was stopped there."
    ),
    GovernanceReason.DAILY_BUDGET_EXCEEDED: (
        "This agent has already spent its daily ceiling. No further runs start until "
        "tomorrow, so one misbehaving agent cannot run up a bill."
    ),
    GovernanceReason.PROVIDER_UNAVAILABLE: (
        "The model provider this agent is configured for could not be reached or "
        "metered. The run stopped rather than falling back to something else."
    ),
    GovernanceReason.UNSUPPORTED_DEFINITION: (
        "This agent's definition asks for a capability this build cannot provide. "
        "Running it anyway would have executed a different agent from the published one."
    ),
    GovernanceReason.AGENT_DECISION: (
        "The agent decided this case belongs with a person and handed it over. That is "
        "the system working, not failing."
    ),
}

#: The reasons that represent the platform **refusing** something, as opposed to an
#: agent legitimately routing a case to a human. Everything here produces a governance
#: step in the trace; ``AGENT_DECISION`` does not.
DENIALS: frozenset[GovernanceReason] = frozenset(
    reason for reason in GovernanceReason if reason is not GovernanceReason.AGENT_DECISION
)


def explain(reason: GovernanceReason) -> str:
    """The human-readable explanation for a reason code."""
    return REASON_EXPLANATION[reason]


# --- Segregation of duties (NFR-5) --------------------------------------------


class Role(StrEnum):
    """The demonstration roles. Not authentication — an actor, declared in a header."""

    CONFIGURATOR = "configurator"
    """Builds the platform's behaviour: authors agent definitions, publishes versions,
    ingests knowledge, starts runs."""

    APPROVER = "approver"
    """Decides the actions runs propose. Deliberately cannot change what the agent is
    allowed to do — that is the whole point of the separation."""

    VIEWER = "viewer"
    """Reads. The audit trail is meant to be readable by people who cannot touch it."""


class Permission(StrEnum):
    """One capability of the API, granted to roles rather than to endpoints."""

    READ = "read"
    AGENT_CONFIGURE = "agent.configure"
    AGENT_PUBLISH = "agent.publish"
    RUN_START = "run.start"
    APPROVAL_DECIDE = "approval.decide"


#: Who holds what. The matrix is the enforcement point for NFR-5 — endpoints ask for a
#: permission, never for a role, so adding an endpoint cannot quietly widen a role.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.CONFIGURATOR: frozenset(
        {
            Permission.READ,
            Permission.AGENT_CONFIGURE,
            Permission.AGENT_PUBLISH,
            # Starting a run is an operator action, not an approval: it proposes work,
            # it does not sign anything off.
            Permission.RUN_START,
        }
    ),
    Role.APPROVER: frozenset({Permission.READ, Permission.APPROVAL_DECIDE}),
    Role.VIEWER: frozenset({Permission.READ}),
}

#: Pairs of permissions that no single role may hold at once. This is NFR-5 written as
#: data: the person who decides what an agent is allowed to do must not also be the
#: person who approves what it then proposes. Compliance's requirement is a property of
#: the matrix, not a promise in a document.
INCOMPATIBLE_DUTIES: tuple[tuple[Permission, Permission], ...] = (
    (Permission.AGENT_CONFIGURE, Permission.APPROVAL_DECIDE),
    (Permission.AGENT_PUBLISH, Permission.APPROVAL_DECIDE),
)


class SegregationOfDutiesError(Exception):
    """The permission matrix grants one role two duties that must stay apart."""


def segregation_violations() -> list[str]:
    """Return every role that holds an incompatible pair of permissions."""
    return [
        f"{role} holds both {first} and {second}"
        for role, held in ROLE_PERMISSIONS.items()
        for first, second in INCOMPATIBLE_DUTIES
        if first in held and second in held
    ]


def _assert_segregated() -> None:
    """Refuse to import a build whose permission matrix violates NFR-5.

    Deliberately an import-time check and deliberately not an ``assert`` (which ``-O``
    strips): a segregation-of-duties failure must stop the process, not warn in a log
    nobody reads. Compliance holds a veto here — "fail-closed or it doesn't ship".
    """
    violations = segregation_violations()
    if violations:  # pragma: no cover - unreachable unless the matrix above is edited
        raise SegregationOfDutiesError(
            "ROLE_PERMISSIONS violates segregation of duties (NFR-5): " + "; ".join(violations)
        )


_assert_segregated()


def permissions_for(role: Role) -> frozenset[Permission]:
    """What a role may do."""
    return ROLE_PERMISSIONS[role]
