"""Tests for ToolServer."""

import pytest

from convilyn_author import ConvilynServer, ToolServer


def _make_server():
    server = ToolServer(
        name="test-server",
        description="A test server",
        version="0.1.0",
        capabilities=["testing"],
    )

    @server.tool(description="Echo input back", idempotent=True)
    async def echo(message: str) -> dict:
        return {"echo": message}

    @server.tool(description="Add two numbers", name="add_numbers")
    async def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    return server


class TestServerCreation:
    def test_server_metadata(self):
        server = _make_server()
        assert server.name == "test-server"
        assert server.description == "A test server"
        assert server.version == "0.1.0"

    def test_capabilities(self):
        server = _make_server()
        assert "testing" in server.capabilities

    def test_backward_compat_alias(self):
        """ConvilynServer is an alias for ToolServer."""
        server = ConvilynServer(name="t", description="t", version="0.1.0")
        assert isinstance(server, ToolServer)


class TestToolRegistration:
    def test_tool_names(self):
        server = _make_server()
        assert "echo" in server.tool_names
        assert "add_numbers" in server.tool_names

    def test_tool_count(self):
        server = _make_server()
        assert len(server.tool_names) == 2

    def test_tool_lookup(self):
        server = _make_server()
        tool = server.get_tool("echo")
        assert tool is not None
        assert tool.description == "Echo input back"
        assert tool.idempotent is True

    def test_tool_not_found(self):
        server = _make_server()
        assert server.get_tool("nonexistent") is None

    def test_custom_tool_name(self):
        server = _make_server()
        tool = server.get_tool("add_numbers")
        assert tool is not None


class TestToolInvocation:
    @pytest.mark.asyncio
    async def test_call_echo(self):
        server = _make_server()
        result = await server.call_tool("echo", {"message": "hello"})
        assert result == {"echo": "hello"}

    @pytest.mark.asyncio
    async def test_call_add(self):
        server = _make_server()
        result = await server.call_tool("add_numbers", {"a": 3, "b": 4})
        assert result == {"sum": 7}

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self):
        server = _make_server()
        with pytest.raises(ValueError, match="not found"):
            await server.call_tool("nonexistent", {})


class TestDataStore:
    def test_data_store_lazy_init(self):
        server = _make_server()
        assert server._data_store is None
        store = server.data_store
        assert store is not None
        assert server._data_store is store

    @pytest.mark.asyncio
    async def test_data_store_roundtrip(self):
        server = _make_server()
        ref_id = await server.data_store.store({"key": "value"})
        assert ref_id.startswith("td_")
        data = await server.data_store.get(ref_id)
        assert data == {"key": "value"}


class TestInputSchema:
    def test_required_params(self):
        server = _make_server()
        tool = server.get_tool("echo")
        schema = tool.input_schema
        assert "message" in schema["required"]

    def test_optional_params(self):
        server = ToolServer(name="t", description="t", version="0.1.0")

        @server.tool(description="test")
        async def greet(name: str, greeting: str = "Hello") -> dict:
            return {"msg": f"{greeting}, {name}"}

        tool = server.get_tool("greet")
        schema = tool.input_schema
        assert "name" in schema["required"]
        assert "greeting" not in schema.get("required", [])
        assert schema["properties"]["greeting"]["default"] == "Hello"

    def test_type_mapping(self):
        server = _make_server()
        tool = server.get_tool("add_numbers")
        schema = tool.input_schema
        assert schema["properties"]["a"]["type"] == "integer"
        assert schema["properties"]["b"]["type"] == "integer"


class TestRepr:
    def test_repr(self):
        server = _make_server()
        r = repr(server)
        assert "test-server" in r
        assert "echo" in r
