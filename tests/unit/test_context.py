"""Tests for ``convilyn_author.context``.

Four categories per the unit-testing skill:
  * logic       — happy paths (request_id, data_store, progress)
  * boundary    — percent bounds (0 / 100)
  * error       — percent outside 0..100 raises ValueError
  * object-state — progress-backend default + custom-override resolution
"""

from __future__ import annotations

import pytest

from convilyn_author.context import (
    ConsoleProgressBackend,
    ProgressBackend,
    ToolContext,
    create_tool_context,
)
from convilyn_author.data_store import InMemoryDataStore


class _RecordingBackend:
    """Test double that records the last (request_id, percent, message) call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def report(self, request_id: str, percent: int, message: str) -> None:
        self.calls.append((request_id, percent, message))


# ── ToolContext properties ─────────────────────────────────────────


class TestToolContextProperties:
    def test_request_id_returns_constructor_argument(self) -> None:
        # logic: request_id round-trips through the constructor
        ctx = ToolContext(request_id="r-123", data_store=InMemoryDataStore())
        assert ctx.request_id == "r-123"

    def test_data_store_returns_constructor_argument(self) -> None:
        # logic: data_store property exposes the store identity-equal
        store = InMemoryDataStore()
        ctx = ToolContext(request_id="r-1", data_store=store)
        assert ctx.data_store is store


# ── ToolContext.report_progress ────────────────────────────────────


class TestToolContextReportProgress:
    def test_report_progress_forwards_to_backend(self) -> None:
        # logic: the backend receives (request_id, percent, message) tuple
        backend = _RecordingBackend()
        ctx = ToolContext(
            request_id="r-1",
            data_store=InMemoryDataStore(),
            progress_backend=backend,
        )
        ctx.report_progress(50, "halfway")
        assert backend.calls == [("r-1", 50, "halfway")]

    def test_zero_percent_is_allowed(self) -> None:
        # boundary: percent == 0 is the lower edge of the legal range
        backend = _RecordingBackend()
        ctx = ToolContext(
            request_id="r-edge",
            data_store=InMemoryDataStore(),
            progress_backend=backend,
        )
        ctx.report_progress(0, "starting")
        assert backend.calls[-1][1] == 0

    def test_hundred_percent_is_allowed(self) -> None:
        # boundary: percent == 100 is the upper edge of the legal range
        backend = _RecordingBackend()
        ctx = ToolContext(
            request_id="r-edge",
            data_store=InMemoryDataStore(),
            progress_backend=backend,
        )
        ctx.report_progress(100, "done")
        assert backend.calls[-1][1] == 100

    def test_negative_percent_raises_value_error(self) -> None:
        # error: below-range percent rejected with a descriptive message
        ctx = ToolContext(request_id="r-1", data_store=InMemoryDataStore())
        with pytest.raises(ValueError, match="0-100"):
            ctx.report_progress(-1, "bad")

    def test_percent_above_hundred_raises_value_error(self) -> None:
        # error: above-range percent rejected with a descriptive message
        ctx = ToolContext(request_id="r-1", data_store=InMemoryDataStore())
        with pytest.raises(ValueError, match="0-100"):
            ctx.report_progress(101, "bad")


# ── Default backend resolution ─────────────────────────────────────


class TestToolContextDefaultBackend:
    def test_default_backend_is_console_when_none_passed(self) -> None:
        # object-state: ToolContext supplies a ConsoleProgressBackend default
        ctx = ToolContext(request_id="r-1", data_store=InMemoryDataStore())
        # report_progress must not raise even without an explicit backend
        ctx.report_progress(10, "ok")

    def test_console_backend_satisfies_progress_protocol(self) -> None:
        # object-state: the default backend conforms to ProgressBackend
        assert isinstance(ConsoleProgressBackend(), ProgressBackend)


# ── create_tool_context factory ────────────────────────────────────


class TestCreateToolContext:
    def test_extracts_request_id_from_payload(self) -> None:
        # logic: payload's request_id is preserved by the factory
        ctx = create_tool_context(
            data_store=InMemoryDataStore(),
            context_payload={"request_id": "from-payload"},
        )
        assert ctx.request_id == "from-payload"

    def test_unknown_when_payload_missing(self) -> None:
        # boundary: no payload at all → request_id falls back to "unknown"
        ctx = create_tool_context(data_store=InMemoryDataStore())
        assert ctx.request_id == "unknown"

    def test_unknown_when_payload_omits_request_id(self) -> None:
        # boundary: partial payload without request_id → "unknown"
        ctx = create_tool_context(
            data_store=InMemoryDataStore(),
            context_payload={"other": "value"},
        )
        assert ctx.request_id == "unknown"

    def test_passes_data_store_through(self) -> None:
        # object-state: factory keeps the same store identity
        store = InMemoryDataStore()
        ctx = create_tool_context(data_store=store)
        assert ctx.data_store is store
