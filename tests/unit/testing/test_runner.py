"""Tests for the local test runner."""

import pytest

from convilyn_author import ToolServer
from convilyn_author.testing import ConvilynTestRunner, assert_tool_error, assert_tool_success


def _make_server():
    server = ToolServer(
        name="runner-test",
        description="Test server for runner",
        version="0.1.0",
    )

    @server.tool(description="Greet someone")
    async def greet(name: str) -> dict:
        return {"greeting": f"Hello, {name}!"}

    @server.tool(description="No-args tool")
    async def ping() -> dict:
        return {"pong": True}

    return server


class TestConvilynTestRunner:
    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        runner = ConvilynTestRunner(server=_make_server())
        result = await runner.call_tool("greet", {"name": "World"})
        assert_tool_success(result)
        assert result.data["greeting"] == "Hello, World!"

    @pytest.mark.asyncio
    async def test_call_tool_tracks_time(self):
        runner = ConvilynTestRunner(server=_make_server())
        result = await runner.call_tool("ping", {})
        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self):
        runner = ConvilynTestRunner(server=_make_server())
        result = await runner.call_tool("nonexistent", {})
        assert_tool_error(result)

    @pytest.mark.asyncio
    async def test_compliance_check_passes(self):
        runner = ConvilynTestRunner(server=_make_server())
        report = await runner.run_compliance_check()
        assert report.all_passed

    @pytest.mark.asyncio
    async def test_compliance_check_no_tools(self):
        empty = ToolServer(name="empty", description="Empty", version="0.1.0")
        runner = ConvilynTestRunner(server=empty)
        report = await runner.run_compliance_check()
        assert not report.all_passed
        assert any("no tools" in r.message.lower() for r in report.failed)

    @pytest.mark.asyncio
    async def test_compliance_check_no_name(self):
        bad = ToolServer(name="", description="No name", version="0.1.0")

        @bad.tool(description="test")
        async def t(x: str) -> dict:
            return {"x": x}

        runner = ConvilynTestRunner(server=bad)
        report = await runner.run_compliance_check()
        assert not report.all_passed

    @pytest.mark.asyncio
    async def test_compliance_includes_data_store_check(self):
        runner = ConvilynTestRunner(server=_make_server())
        report = await runner.run_compliance_check()
        check_names = [r.check_name for r in report.results]
        assert "get_tool_data" in check_names
