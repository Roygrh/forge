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
from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.base import LlmAdapter
from app.llm.adapters.demo import SkeletonDemoAdapter
from app.llm.contract import AdapterError
from app.llm.gateway import LlmGateway
from app.tools.gateway import ToolGateway

Role = Literal["configurator", "approver", "viewer"]


def get_llm_gateway() -> LlmGateway:
    """Build the process-wide LLM gateway.

    The Anthropic adapter is registered only when a key is configured; without one the
    platform still runs end to end on the fake, and a DNA that names ``anthropic``
    escalates with ``provider_unavailable`` rather than failing obscurely at call time.
    """
    adapters: list[LlmAdapter] = [
        # Serves the seeded skeleton agent (DNA provider "fake") deterministically, so
        # a freshly composed stack demonstrates a full run with no key and no network.
        SkeletonDemoAdapter()
    ]
    if get_settings().anthropic_api_key:
        # A key that is present but unusable leaves the provider unregistered; a DNA
        # naming it then escalates with `provider_unavailable` instead of taking the
        # whole API down at import time.
        with suppress(AdapterError):  # pragma: no cover - needs a broken key to reach
            adapters.append(AnthropicAdapter())
    return LlmGateway(adapters)


def get_tool_gateway() -> ToolGateway:
    """Build the tool gateway over the registry."""
    return ToolGateway()


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
