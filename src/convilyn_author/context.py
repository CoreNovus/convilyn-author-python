"""ToolContext — simplified execution context for tool functions.

Provides access to the data store and progress reporting. All extraction/
artifact/tier concepts have been removed — tools receive data via LLM
arguments and store large results in the DataStore.

ToolContext is optional: if a tool function's first parameter is typed as
``ToolContext``, the runtime injects it automatically.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from convilyn_author.data_store import DataStoreProtocol

logger = logging.getLogger("convilyn_author.context")


@runtime_checkable
class ProgressBackend(Protocol):
    """Backend for reporting tool execution progress."""

    def report(self, request_id: str, percent: int, message: str) -> None: ...


class ConsoleProgressBackend:
    """Dev-mode backend: prints progress to console."""

    def report(self, request_id: str, percent: int, message: str) -> None:
        logger.info("[progress] %s — %d%% %s", request_id, percent, message)


class ToolContext:
    """Execution context injected into tool functions.

    Capabilities:
    - ``data_store`` — store/retrieve large data via ref_id
    - ``report_progress(percent, message)`` — report execution progress

    Example::

        @server.tool(description="Analyze document")
        async def analyze(ctx: ToolContext, text: str) -> dict:
            ctx.report_progress(50, "Analyzing...")
            result = do_analysis(text)
            ref_id = await ctx.data_store.store(result)
            return {"ref_id": ref_id, "summary": "Analysis complete"}
    """

    def __init__(
        self,
        request_id: str,
        data_store: DataStoreProtocol,
        progress_backend: ProgressBackend | None = None,
    ) -> None:
        self._request_id = request_id
        self._data_store = data_store
        self._progress_backend = progress_backend or ConsoleProgressBackend()

    @property
    def request_id(self) -> str:
        """Unique identifier for this tool invocation."""
        return self._request_id

    @property
    def data_store(self) -> DataStoreProtocol:
        """Access the data store for storing/retrieving large results."""
        return self._data_store

    def report_progress(self, percent: int, message: str) -> None:
        """Report tool execution progress.

        Args:
            percent: Progress percentage (0-100).
            message: Human-readable progress message.

        Raises:
            ValueError: If percent is outside 0-100 range.
        """
        if not 0 <= percent <= 100:
            raise ValueError(f"Progress percent must be 0-100, got {percent}")
        self._progress_backend.report(self._request_id, percent, message)


def create_tool_context(
    data_store: DataStoreProtocol,
    context_payload: dict[str, Any] | None = None,
) -> ToolContext:
    """Factory: build a ToolContext from a data store and optional payload."""
    payload = context_payload or {}
    request_id = payload.get("request_id", "unknown")

    return ToolContext(
        request_id=request_id,
        data_store=data_store,
    )
