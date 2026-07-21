"""Tests for ConvilynManifest."""

import json

from convilyn_author import ConvilynManifest, ToolServer


def _make_manifest():
    server = ToolServer(
        name="test-srv",
        description="Test server",
        version="1.0.0",
        capabilities=["testing"],
    )

    @server.tool(description="Tool A", idempotent=True)
    async def tool_a(text: str) -> dict:
        return {"result": text}

    @server.tool(description="Tool B")
    async def tool_b(count: int, label: str = "default") -> dict:
        return {"count": count, "label": label}

    return server.synth()


class TestManifestSynth:
    def test_server_section(self):
        m = _make_manifest()
        assert m.server.name == "test-srv"
        assert m.server.version == "1.0.0"
        assert m.server.description == "Test server"

    def test_tools(self):
        m = _make_manifest()
        assert len(m.tools) == 2
        names = [t.name for t in m.tools]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_tool_schema(self):
        m = _make_manifest()
        tool_b = next(t for t in m.tools if t.name == "tool_b")
        assert "count" in tool_b.input_schema["required"]
        assert "label" not in tool_b.input_schema.get("required", [])
        assert tool_b.idempotent is False

    def test_idempotent_flag(self):
        m = _make_manifest()
        tool_a = next(t for t in m.tools if t.name == "tool_a")
        assert tool_a.idempotent is True

    def test_no_extractions_field(self):
        """Manifest should not have required_extractions."""
        m = _make_manifest()
        d = m.to_dict()
        assert "required_extractions" not in d

    def test_capabilities(self):
        m = _make_manifest()
        assert "testing" in m.capabilities

    def test_sdk_version(self):
        m = _make_manifest()
        assert m.sdk_version == "1.0.0"


class TestManifestSerialization:
    def test_to_json(self):
        m = _make_manifest()
        raw = m.to_json()
        data = json.loads(raw)
        assert data["server"]["name"] == "test-srv"
        assert len(data["tools"]) == 2

    def test_to_dict(self):
        m = _make_manifest()
        d = m.to_dict()
        assert isinstance(d, dict)
        assert d["server"]["name"] == "test-srv"

    def test_roundtrip_json(self):
        m = _make_manifest()
        raw = m.to_json()
        m2 = ConvilynManifest.from_json(raw)
        assert m2.server.name == m.server.name
        assert len(m2.tools) == len(m.tools)

    def test_save_and_load(self, tmp_path):
        m = _make_manifest()
        path = tmp_path / "test.manifest.json"
        m.save(path)
        m2 = ConvilynManifest.load(path)
        assert m2.server.name == m.server.name
        assert m2.to_dict() == m.to_dict()
