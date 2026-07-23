"""Base contract for AI protocol adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai.contracts import CompletionRequest, CompletionResult, RouteTarget


class CompletionAdapter(ABC):
    """Turns a resolved route and a vendor-neutral request into a completion."""

    driver: str

    @abstractmethod
    def preflight(
        self,
        request: CompletionRequest,
        route: RouteTarget,
    ) -> None:
        """Validate local request/route preparation without contacting a provider.

        The gateway calls this before it records a billable attempt.  An adapter
        must therefore raise here for every deterministic configuration or
        serialization error that would otherwise happen before network I/O.
        """

    @abstractmethod
    def complete(
        self,
        request: CompletionRequest,
        route: RouteTarget,
    ) -> CompletionResult:
        """Execute one external request or raise ``ProviderError``."""


__all__ = ["CompletionAdapter"]
