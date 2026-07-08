"""Tests for JSON-RPC protocol adapter."""

import pytest

from convilyn_sdk import ToolServer
from convilyn_sdk._internal.models import JSONRPCRequest
from convilyn_sdk._internal.protocol import handle_jsonrpc_request


def _make_server():
    server = ToolServer(name="proto-test", description="Test", version="0.1.0")

    @server.tool(description="Echo tool")
    async def echo(message: str) -> dict:
        return {"echo": message}

    @server.tool(description="Failing tool")
    async def fail_tool(reason: str) -> dict:
        raise RuntimeError(reason)

    return server


class TestProtocol:
    @pytest.mark.asyncio
    async def test_tools_call(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"message": "hi"}},
            id="req-1",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is None
        assert response.result["success"] is True
        assert response.result["data"]["echo"] == "hi"
        assert response.id == "req-1"

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        server = _make_server()
        request = JSONRPCRequest(method="unknown/method", id="req-2")
        response = await handle_jsonrpc_request(request, server)
        assert response.error is not None
        assert response.error.code == -32601

    @pytest.mark.asyncio
    async def test_missing_tool_name(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"arguments": {}},
            id="req-3",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is not None
        assert response.error.code == -32602

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "nonexistent", "arguments": {}},
            id="req-4",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is not None
        assert response.error.code == -32601

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "fail_tool", "arguments": {"reason": "test error"}},
            id="req-5",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is None  # JSON-RPC level OK
        assert response.result["success"] is False
        assert "execution failed" in response.result["error"]["message"]

    @pytest.mark.asyncio
    async def test_execution_time_tracked(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"message": "timing"}},
            id="req-6",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.result["execution_time_ms"] is not None
        assert response.result["execution_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_get_tool_data_builtin(self):
        """get_tool_data should be handled by protocol layer."""
        server = _make_server()
        # First store some data
        ref_id = await server.data_store.store({"key": "value"})

        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "get_tool_data", "arguments": {"ref_id": ref_id}},
            id="req-7",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is None
        assert response.result["success"] is True
        assert response.result["data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_get_tool_data_not_found(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "get_tool_data", "arguments": {"ref_id": "td_000000000000"}},
            id="req-8",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is None
        assert response.result["success"] is False

    @pytest.mark.asyncio
    async def test_get_tool_data_missing_ref_id(self):
        server = _make_server()
        request = JSONRPCRequest(
            method="tools/call",
            params={"name": "get_tool_data", "arguments": {}},
            id="req-9",
        )
        response = await handle_jsonrpc_request(request, server)
        assert response.error is not None
        assert response.error.code == -32602
