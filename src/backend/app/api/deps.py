"""Shared API dependencies: the gateways, and the demonstration role header.

The two gateways are dependencies rather than module globals for one reason: a test
overrides ``get_llm_gateway`` to install a scripted :class:`FakeAdapter` and gets a
fully deterministic run through the real HTTP surface, with no seam between what the
test exercises and what the demo runs.
"""

from contextlib import suppress
from typing import Annotated, Literal

from fastapi import Depends, Header

from app.config import get_settings
from app.db import SessionDep
from app.erp.store import get_erp
from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.base import LlmAdapter
from app.llm.adapters.demo import MeridianDemoAdapter
from app.llm.contract import AdapterError
from app.llm.gateway import LlmGateway
from app.rules.repository import load_rule_set
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry, build_tools

Role = Literal["configurator", "approver", "viewer"]


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


def require_role(
    x_forge_role: Annotated[
        Role,
        Header(
            description=(
                "Demonstration role for segregation of duties (NFR-5). Not authentication."
            )
        ),
    ],
) -> str:
    """Validate the demonstration role header and return it as the acting identity.

    Phase 3.2 checks only that the header names a known role, and records it as the
    event actor. Per-operation permission enforcement (the 403s in openapi.yaml) lands
    with the approval and publish endpoints, where there is something to segregate.
    """
    return f"role:{x_forge_role}"


LlmGatewayDep = Annotated[LlmGateway, Depends(get_llm_gateway)]
ToolGatewayDep = Annotated[ToolGateway, Depends(get_tool_gateway)]
ActorDep = Annotated[str, Depends(require_role)]
