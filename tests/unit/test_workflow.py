"""Tests for WorkflowSpec fluent builder — 100% coverage."""

import json
import tempfile
from pathlib import Path

from convilyn_sdk import ToolServer, WorkflowSpec


def _make_server():
    server = ToolServer(name="test-srv", description="Test", version="0.1.0")

    @server.tool(description="Process text")
    async def process(text: str) -> dict:
        return {"result": text}

    @server.tool(description="Summarize text")
    async def summarize(text: str) -> dict:
        return {"summary": text[:50]}

    return server


# ── Construction & Identity ─────────────────────────────────────


class TestWorkflowSpecConstruction:
    def test_minimal_spec(self):
        w = WorkflowSpec("test_wf", name="Test WF")
        assert w._spec_id == "test_wf"
        assert w._name == "Test WF"
        assert w._version == "1.0.0"
        assert w._category == "goal_lane"
        assert w._platform == "multi"

    def test_custom_version_and_category(self):
        w = WorkflowSpec("x", name="X", version="2.5.0", category="ads", platform="meta")
        assert w._version == "2.5.0"
        assert w._category == "ads"
        assert w._platform == "meta"

    def test_with_description(self):
        w = WorkflowSpec("x", name="X").with_description("Hello")
        assert w._description == "Hello"

    def test_with_description_i18n(self):
        w = WorkflowSpec("x", name="X").with_description_i18n({"en": "English", "zh": "Chinese"})
        assert w._description_i18n == {"en": "English", "zh": "Chinese"}

    def test_with_aliases(self):
        w = WorkflowSpec("x", name="X").with_aliases("A", "B")
        assert w._aliases == ["A", "B"]

    def test_with_keywords(self):
        w = WorkflowSpec("x", name="X").with_keywords("k1", "k2")
        assert w._keywords == ["k1", "k2"]

    def test_repr(self):
        w = WorkflowSpec("x", name="X")
        r = repr(w)
        assert "WorkflowSpec" in r
        assert "x" in r
        assert "X" in r


# ── Immutability ────────────────────────────────────────────────


class TestImmutability:
    def test_with_description_returns_new_instance(self):
        w1 = WorkflowSpec("x", name="X")
        w2 = w1.with_description("Desc")
        assert w1._description is None
        assert w2._description == "Desc"
        assert w1 is not w2

    def test_add_phase_returns_new_instance(self):
        w1 = WorkflowSpec("x", name="X")
        w2 = w1.add_phase("P1", "Do things")
        assert len(w1._phases) == 0
        assert len(w2._phases) == 1

    def test_use_tools_returns_new_instance(self):
        w1 = WorkflowSpec("x", name="X")
        w2 = w1.use_tools("s:t")
        assert len(w1._mcp_config.tools) == 0
        assert len(w2._mcp_config.tools) == 1

    def test_chain_operations_independent(self):
        base = WorkflowSpec("x", name="X")
        branch_a = base.add_phase("A", "Phase A")
        branch_b = base.add_phase("B", "Phase B")
        assert len(branch_a._phases) == 1
        assert len(branch_b._phases) == 1
        assert branch_a._phases[0].phase == "A"
        assert branch_b._phases[0].phase == "B"


# ── Input Configuration ─────────────────────────────────────────


class TestInputConfig:
    def test_with_input_basic(self):
        w = WorkflowSpec("x", name="X").with_input(types=["document"], formats=["pdf"])
        assert w._input.types == ["document"]
        assert w._input.formats == ["pdf"]
        assert w._input.max_size_bytes == 10_485_760

    def test_with_input_all_fields(self):
        w = WorkflowSpec("x", name="X").with_input(
            types=["video"],
            formats=["mp4"],
            max_size_bytes=1_000_000,
            max_duration_seconds=300,
            min_duration_seconds=10,
            min_file_count=2,
        )
        assert w._input.max_duration_seconds == 300
        assert w._input.min_duration_seconds == 10
        assert w._input.min_file_count == 2

    def test_with_input_no_formats(self):
        w = WorkflowSpec("x", name="X").with_input(types=["audio"])
        assert w._input.formats is None


# ── Output Configuration ────────────────────────────────────────


class TestOutputConfig:
    def test_with_output_single(self):
        w = WorkflowSpec("x", name="X").with_output(format="json", type="analysis")
        assert len(w._outputs) == 1
        assert w._outputs[0].format == "json"
        assert w._outputs[0].additional == {"type": "analysis"}

    def test_with_output_chained(self):
        w = (
            WorkflowSpec("x", name="X")
            .with_output(format="txt", type="text")
            .with_output(format="pdf", type="rendered")
        )
        assert len(w._outputs) == 2
        assert w._outputs[0].format == "txt"
        assert w._outputs[1].format == "pdf"


# ── MCP Tool Composition ────────────────────────────────────────


class TestMCPConfig:
    def test_use_tools(self):
        w = WorkflowSpec("x", name="X").use_tools("s1:t1", "s2:t2")
        assert w._mcp_config.tools == ["s1:t1", "s2:t2"]

    def test_use_tools_dedup(self):
        w = WorkflowSpec("x", name="X").use_tools("s:t1").use_tools("s:t1", "s:t2")
        assert w._mcp_config.tools == ["s:t1", "s:t2"]

    def test_use_servers(self):
        w = WorkflowSpec("x", name="X").use_servers("srv1", "srv2")
        assert w._mcp_config.mcp_servers == ["srv1", "srv2"]

    def test_use_servers_dedup(self):
        w = WorkflowSpec("x", name="X").use_servers("s").use_servers("s", "s2")
        assert w._mcp_config.mcp_servers == ["s", "s2"]

    def test_from_server(self):
        server = _make_server()
        w = WorkflowSpec("x", name="X").from_server(server)
        assert "test-srv" in w._mcp_config.mcp_servers
        assert "test-srv:process" in w._mcp_config.tools
        assert "test-srv:summarize" in w._mcp_config.tools


# ── Agent Configuration ─────────────────────────────────────────


class TestAgentConfig:
    def test_with_agent_config(self):
        w = WorkflowSpec("x", name="X").with_agent_config(max_iterations=15, temperature=0.5)
        assert w._agent_config is not None
        assert w._agent_config.max_iterations == 15
        assert w._agent_config.temperature == 0.5
        # Prompt-template selection is server-side; not a public field.
        assert not hasattr(w._agent_config, "system_prompt_id")

    def test_with_agent_config_custom_prompt(self):
        w = WorkflowSpec("x", name="X").with_agent_config(system_prompt="Custom prompt text")
        assert w._agent_config.system_prompt == "Custom prompt text"


# ── Phases ──────────────────────────────────────────────────────


class TestPhases:
    def test_add_phase(self):
        w = WorkflowSpec("x", name="X").add_phase("Parse", "Parse the file.")
        assert len(w._phases) == 1
        assert w._phases[0].phase == "Parse"
        assert w._phases[0].description == "Parse the file."

    def test_add_multiple_phases(self):
        w = (
            WorkflowSpec("x", name="X")
            .add_phase("A", "First")
            .add_phase("B", "Second")
            .add_phase("C", "Third")
        )
        assert len(w._phases) == 3
        assert [p.phase for p in w._phases] == ["A", "B", "C"]


# ── Slots ───────────────────────────────────────────────────────


class TestSlots:
    def test_add_required_slot(self):
        w = WorkflowSpec("x", name="X").add_slot(
            "lang", "choice", "Select language", required=True, options=["en", "zh"]
        )
        assert len(w._required_slots) == 1
        assert len(w._optional_slots) == 0
        assert w._required_slots[0].slot_id == "lang"

    def test_add_optional_slot(self):
        w = WorkflowSpec("x", name="X").add_slot("tone", "text", "Describe tone", required=False)
        assert len(w._optional_slots) == 1
        assert len(w._required_slots) == 0

    def test_add_slot_with_kwargs(self):
        w = WorkflowSpec("x", name="X").add_slot(
            "s1", "boolean", "Enable?", default=True, hidden=True
        )
        assert w._optional_slots[0].default is True
        assert w._optional_slots[0].hidden is True


# ── Preflight Rules ─────────────────────────────────────────────


class TestPreflightRules:
    def test_add_preflight_rule(self):
        w = WorkflowSpec("x", name="X").add_preflight_rule(
            "r1",
            check_type="file_count",
            params={"min": 1},
            error_message="Need file",
        )
        assert len(w._preflight_rules) == 1
        assert w._preflight_rules[0].rule_id == "r1"
        assert w._preflight_rules[0].is_blocking is True

    def test_add_non_blocking_rule(self):
        w = WorkflowSpec("x", name="X").add_preflight_rule(
            "r2",
            check_type="file_format",
            params={"allowed": ["pdf"]},
            error_message="Preferred PDF",
            is_blocking=False,
        )
        assert w._preflight_rules[0].is_blocking is False


# ── Locale Policy ───────────────────────────────────────────────


class TestLocalePolicy:
    def test_default_locale_policy(self):
        w = WorkflowSpec("x", name="X")
        assert w._locale_policy.type == "locale_independent"

    def test_locale_bound(self):
        w = WorkflowSpec("x", name="X").with_locale_policy(
            type="locale_bound",
            locale_market_map={"en": "us", "zh": "taiwan"},
            prompt_hint="Use {locale} conventions",
        )
        assert w._locale_policy.type == "locale_bound"
        assert w._locale_policy.locale_market_map["zh"] == "taiwan"
        assert w._locale_policy.prompt_hint is not None

    def test_locale_with_affected_slots(self):
        w = WorkflowSpec("x", name="X").with_locale_policy(affected_slots=["region"])
        assert w._locale_policy.affected_slots == ["region"]


# ── Compile ─────────────────────────────────────────────────────


class TestCompile:
    def test_compile_minimal(self):
        compiled = WorkflowSpec("test", name="Test").compile()
        assert compiled["spec_id"] == "test"
        assert compiled["name"] == "Test"
        assert compiled["version"] == "1.0.0"
        # Public blueprint carries a schema version for the server translator.
        assert compiled["public_schema_version"] == "1"

    def test_compile_omits_internal_fields(self):
        # The public blueprint must NOT carry platform-internal / engine
        # fields — those are filled in server-side by the translator.
        compiled = WorkflowSpec("x", name="X").compile()
        for leaked in (
            "category",
            "platform",
            "status",
            "sku_group",
            "priority",
            "subcategory",
            "variant",
            "default_steps",
        ):
            assert leaked not in compiled

    def test_compile_excludes_none(self):
        compiled = WorkflowSpec("x", name="X").compile()
        assert "description" not in compiled
        assert "description_i18n" not in compiled
        assert "mcp_config" not in compiled  # empty tools → excluded
        assert "phases" not in compiled  # no phases → excluded

    def test_compile_includes_mcp_when_tools_exist(self):
        compiled = WorkflowSpec("x", name="X").use_tools("s:t").use_servers("s").compile()
        assert "mcp_config" in compiled
        assert compiled["mcp_config"]["tools"] == ["s:t"]

    def test_compile_full_workflow(self):
        server = _make_server()
        compiled = (
            WorkflowSpec("test_wf", name="Full WF", version="2.0.0")
            .with_description("A full workflow")
            .with_description_i18n({"en": "En", "zh": "Zh"})
            .with_input(types=["document"], formats=["pdf"])
            .with_output(format="json", type="result")
            .from_server(server)
            .add_phase("Phase1", "Do stuff")
            .with_agent_config(max_iterations=20)
            .add_preflight_rule("r", check_type="file_count", params={"min": 1}, error_message="E")
            .add_slot("s1", "text", "Question?")
            .with_locale_policy(type="locale_independent")
            .with_aliases("Alias1")
            .with_keywords("kw1")
            .compile()
        )

        assert compiled["spec_id"] == "test_wf"
        assert compiled["version"] == "2.0.0"
        assert compiled["description"] == "A full workflow"
        assert compiled["description_i18n"]["zh"] == "Zh"
        assert compiled["supported_input_types"] == ["document"]
        assert compiled["supported_input_formats"] == ["pdf"]
        assert compiled["max_input_size_bytes"] == 10_485_760
        assert len(compiled["output_specs"]) == 1
        assert len(compiled["mcp_config"]["tools"]) == 2
        assert len(compiled["phases"]) == 1
        assert compiled["agent_config"]["max_iterations"] == 20
        assert len(compiled["preflight_rules"]) == 1
        assert len(compiled["optional_slots"]) == 1
        assert compiled["aliases"] == ["Alias1"]
        assert compiled["keywords"] == ["kw1"]


# ── File I/O ────────────────────────────────────────────────────


class TestFileIO:
    def test_save_and_load_roundtrip(self):
        w = (
            WorkflowSpec("rt_test", name="Roundtrip", version="1.2.3")
            .with_description("Testing save/load")
            .with_input(types=["document"], formats=["pdf"])
            .with_output(format="txt")
            .use_tools("s:t1")
            .use_servers("s")
            .add_phase("P1", "Phase 1 desc")
            .with_agent_config(max_iterations=10, temperature=0.7)
            .add_preflight_rule("r", check_type="file_count", params={"min": 1}, error_message="E")
            .add_slot("s1", "text", "Q?")
            .with_locale_policy(type="locale_bound", locale_market_map={"en": "us"})
            .with_aliases("A1")
            .with_keywords("k1")
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.spec.json"
            w.save(path)

            assert path.exists()
            data = json.loads(path.read_text())
            assert data["spec_id"] == "rt_test"

            loaded = WorkflowSpec.load(str(path))
            recompiled = loaded.compile()

            assert recompiled["spec_id"] == "rt_test"
            assert recompiled["version"] == "1.2.3"
            assert recompiled["description"] == "Testing save/load"
            assert len(recompiled["mcp_config"]["tools"]) == 1
            assert len(recompiled["phases"]) == 1
            assert recompiled["agent_config"]["max_iterations"] == 10

    def test_save_default_path(self):
        w = WorkflowSpec("x", name="X")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "workflow.spec.json"
            result = w.save(str(path))
            assert result == path
            assert path.exists()

    def test_load_preserves_all_fields(self):
        original = (
            WorkflowSpec("load_test", name="Load", version="3.0.0")
            .with_description("Round-trip")
            .with_aliases("A1")
            .with_keywords("k1")
            .with_input(types=["document"], formats=["pdf"])
            .add_phase("P1", "desc")
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            original.save(path)
            loaded = WorkflowSpec.load(str(path))

            assert loaded._spec_id == "load_test"
            assert loaded._version == "3.0.0"
            assert loaded._description == "Round-trip"
            assert loaded._aliases == ["A1"]
            assert loaded._keywords == ["k1"]
            assert loaded._phases[0].phase == "P1"
