"""Shared API dependencies: the gateways, the clock, and the acting role.

The gateways are dependencies rather than module globals for one reason: a test
overrides ``get_llm_gateway`` to install a scripted :class:`FakeAdapter` and gets a
fully deterministic run through the real HTTP surface, with no seam between what the
test exercises and what the demo runs.

The role header becomes an :class:`Actor` here — a role plus the permissions that role
holds. Endpoints ask for a **permission**, never for a role, so widening what a role may
do is a change to one matrix in :mod:`app.governance` and not a change scattered across
handlers (NFR-5).
"""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, status

from app.api.errors import ApiError
from app.approvals import ApprovalQueue
from app.config import get_settings
from app.db import SessionDep
from app.erp.store import get_erp
from app.governance import Permission, Role, permissions_for
from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.base import LlmAdapter
from app.llm.adapters.demo import MeridianDemoAdapter
from app.llm.contract import AdapterError
from app.llm.gateway import LlmGateway
from app.rules.repository import load_rule_set
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry, build_tools


def get_llm_gateway() -> LlmGateway:
    """Build the process-wide LLM gateway.

    The Anthropic adapter is registered only when a key is configured; without one the
    platform still runs end to end on the fake, and a DNA that names ``anthropic``
    escalates with ``provider_unavailable`` rather than failing obscurely at call time.
    """
    adapters: list[LlmAdapter] = [
        # Serves the seeded AP agents (DNA provider "fake") deterministically, so a
        # freshly composed stack demonstrates a full run with no key and no network.
        MeridianDemoAdapter()
    ]
    if get_settings().anthropic_api_key:
        # A key that is present but unusable leaves the provider unregistered; a DNA
        # naming it then escalates with `provider_unavailable` instead of taking the
        # whole API down at import time.
        with suppress(AdapterError):  # pragma: no cover - needs a broken key to reach
            adapters.append(AnthropicAdapter())
    return LlmGateway(adapters)


async def get_tool_gateway(session: SessionDep) -> ToolGateway:
    """Build the tool gateway over a registry bound to the rules in force *now*.

    The rule set is read from the database on every request rather than cached at
    import. That is the whole mechanism behind "a rule change needs no redeploy": edit a
    row in ``rules`` and the next run is evaluated against it, with no cache to
    invalidate and no image to rebuild (see :mod:`app.rules`). A few dozen rows per run
    is a cost worth paying for a property that obvious.
    """
    rule_set = await load_rule_set(session)
    return ToolGateway(ToolRegistry(build_tools(erp=get_erp(), rule_set=rule_set)))


def get_clock() -> Callable[[], datetime]:
    """The clock the runtime measures ``guardrails.timeout_seconds`` against.

    A dependency, not ``datetime.now`` inline, so the wall-clock guardrail can be tested
    at the HTTP boundary like every other limit — a governance control that can only be
    verified by waiting for it is a control nobody verifies.
    """
    return lambda: datetime.now(UTC)


# --- Who is acting, and what they may do (NFR-5) ------------------------------


@dataclass(frozen=True)
class Actor:
    """The identity a request acts under, and the permissions it carries.

    Not authentication: the role arrives in a header and is trusted. What *is* real is
    the mapping from role to permission and the refusal that follows from it — the
    demonstration is of segregation of duties, which is a matrix question, not a
    credentials question.
    """

    role: Role

    @property
    def identity(self) -> str:
        """How this actor is recorded in the audit log."""
        return f"role:{self.role}"

    def allows(self, permission: Permission) -> bool:
        """Whether this actor holds ``permission``."""
        return permission in permissions_for(self.role)

    def require(self, permission: Permission) -> None:
        """Raise 403 unless this actor holds ``permission``."""
        if not self.allows(permission):
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "permission_denied",
                f"role {self.role} may not {permission}",
                {
                    "role": str(self.role),
                    "required_permission": str(permission),
                    "held_permissions": sorted(str(held) for held in permissions_for(self.role)),
                },
            )


def require_role(
    x_forge_role: Annotated[
        Role,
        Header(
            description=(
                "Demonstration role for segregation of duties (NFR-5). Not authentication."
            )
        ),
    ],
) -> Actor:
    """Resolve the demonstration role header into the acting identity.

    An unknown role is a 422 from FastAPI's own validation before this runs: the header
    is an enum in the contract, so "some other role" is not a thing the platform has to
    have an opinion about.
    """
    return Actor(role=x_forge_role)


LlmGatewayDep = Annotated[LlmGateway, Depends(get_llm_gateway)]
ToolGatewayDep = Annotated[ToolGateway, Depends(get_tool_gateway)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
ActorDep = Annotated[Actor, Depends(require_role)]


def get_approval_queue(
    session: SessionDep,
    llm_gateway: LlmGatewayDep,
    tool_gateway: ToolGatewayDep,
    clock: ClockDep,
) -> ApprovalQueue:
    """Build the approval queue over the same gateways and the same clock as a run.

    The gateways are shared with the runtime deliberately: an approved action is executed
    by the *same* tool gateway against the *same* published DNA as the call that was
    parked. Nothing about a human's yes creates a second path to a tool.

    The clock is the injected one for the same reason the runtime's is — expiry is a
    governance control, and a control that can only be verified by waiting twelve hours
    is a control nobody verifies.
    """
    return ApprovalQueue(session, llm_gateway=llm_gateway, tool_gateway=tool_gateway, clock=clock)


ApprovalQueueDep = Annotated[ApprovalQueue, Depends(get_approval_queue)]
