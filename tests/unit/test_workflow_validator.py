"""Tests for workflow_validator — 100% coverage of all validation paths."""


from convilyn_sdk import ToolServer
from convilyn_sdk.workflow_validator import (
    WorkflowValidationResult,
    validate_tool_coverage,
    validate_workflow_spec,
)


def _minimal_valid_spec() -> dict:
    return {
        "spec_id": "test.workflow",
        "name": "Test Workflow",
        "version": "1.0.0",
        "category": "goal_lane",
        "platform": "multi",
        "supported_input_types": ["document"],
        "output_specs": [{"format": "json"}],
        "mcp_config": {
            "mcp_servers": ["my-server"],
            "tools": ["my-server:my_tool"],
        },
        "phases": [
            {"phase": "P1", "description": "Do something."},
        ],
        "agent_config": {
            "max_iterations": 25,
            "temperature": 0.3,
        },
        "required_slots": [],
        "optional_slots": [],
        "preflight_rules": [
            {
                "rule_id": "r1",
                "check_type": "file_count",
                "params": {"min": 1},
                "error_message": "Need file",
            }
        ],
    }


def _make_server(name="my-server", tools=("my_tool",)):
    server = ToolServer(name=name, description="T", version="0.1.0")
    for tool_name in tools:

        @server.tool(description=f"Tool {tool_name}", name=tool_name)
        async def fn(text: str = "x") -> dict:
            return {"ok": True}

    return server


# ── WorkflowValidationResult ────────────────────────────────────


class TestWorkflowValidationResult:
    def test_default_valid(self):
        r = WorkflowValidationResult()
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_add_error(self):
        r = WorkflowValidationResult()
        r.add_error("E1")
        assert r.valid is False
        assert r.errors == ["E1"]

    def test_add_warning(self):
        r = WorkflowValidationResult()
        r.add_warning("W1")
        assert r.valid is True
        assert r.warnings == ["W1"]

    def test_multiple_errors(self):
        r = WorkflowValidationResult()
        r.add_error("E1")
        r.add_error("E2")
        assert len(r.errors) == 2
        assert r.valid is False


# ── validate_workflow_spec ───────────────────────────────────────


class TestValidateWorkflowSpec:
    def test_valid_spec(self):
        result = validate_workflow_spec(_minimal_valid_spec())
        assert result.valid is True
        assert result.errors == []

    def test_missing_spec_id(self):
        spec = _minimal_valid_spec()
        del spec["spec_id"]
        result = validate_workflow_spec(spec)
        assert result.valid is False
        assert any("spec_id" in e for e in result.errors)

    def test_missing_name(self):
        spec = _minimal_valid_spec()
        del spec["name"]
        result = validate_workflow_spec(spec)
        assert result.valid is False
        assert any("name" in e for e in result.errors)

    def test_missing_version(self):
        spec = _minimal_valid_spec()
        del spec["version"]
        result = validate_workflow_spec(spec)
        assert result.valid is False
        assert any("version" in e for e in result.errors)

    def test_empty_spec_id(self):
        spec = _minimal_valid_spec()
        spec["spec_id"] = ""
        result = validate_workflow_spec(spec)
        assert result.valid is False

    def test_invalid_semver(self):
        spec = _minimal_valid_spec()
        spec["version"] = "1.0"
        result = validate_workflow_spec(spec)
        assert any("semver" in e for e in result.errors)

    def test_invalid_spec_id_pattern(self):
        spec = _minimal_valid_spec()
        spec["spec_id"] = "invalid spec id!"
        result = validate_workflow_spec(spec)
        assert any("alphanumeric" in e for e in result.errors)

    def test_invalid_tool_reference_format(self):
        spec = _minimal_valid_spec()
        spec["mcp_config"]["tools"] = ["no_colon_here"]
        result = validate_workflow_spec(spec)
        assert any("server:tool" in e for e in result.errors)

    def test_server_not_listed_in_mcp_servers(self):
        spec = _minimal_valid_spec()
        spec["mcp_config"]["mcp_servers"] = ["other-server"]
        result = validate_workflow_spec(spec)
        assert any("not listed in mcp_servers" in e for e in result.errors)

    def test_no_tools_warning(self):
        spec = _minimal_valid_spec()
        spec["mcp_config"]["tools"] = []
        result = validate_workflow_spec(spec)
        assert any("No tools" in w for w in result.warnings)

    def test_no_mcp_config_ok(self):
        spec = _minimal_valid_spec()
        del spec["mcp_config"]
        result = validate_workflow_spec(spec)
        assert result.valid is True

    def test_phase_missing_name(self):
        spec = _minimal_valid_spec()
        spec["phases"] = [{"description": "D"}]
        result = validate_workflow_spec(spec)
        assert any("Phase 0 missing" in e for e in result.errors)

    def test_phase_empty_description(self):
        spec = _minimal_valid_spec()
        spec["phases"] = [{"phase": "P", "description": ""}]
        result = validate_workflow_spec(spec)
        assert any("empty description" in e for e in result.errors)

    def test_no_phases_warning(self):
        spec = _minimal_valid_spec()
        spec["phases"] = []
        result = validate_workflow_spec(spec)
        assert any("No phases" in w for w in result.warnings)

    def test_agent_config_temperature_too_high(self):
        spec = _minimal_valid_spec()
        spec["agent_config"]["temperature"] = 1.5
        result = validate_workflow_spec(spec)
        assert any("temperature" in e for e in result.errors)

    def test_agent_config_temperature_too_low(self):
        spec = _minimal_valid_spec()
        spec["agent_config"]["temperature"] = -0.1
        result = validate_workflow_spec(spec)
        assert any("temperature" in e for e in result.errors)

    def test_agent_config_iterations_too_high(self):
        spec = _minimal_valid_spec()
        spec["agent_config"]["max_iterations"] = 100
        result = validate_workflow_spec(spec)
        assert any("max_iterations" in e for e in result.errors)

    def test_agent_config_iterations_too_low(self):
        spec = _minimal_valid_spec()
        spec["agent_config"]["max_iterations"] = 0
        result = validate_workflow_spec(spec)
        assert any("max_iterations" in e for e in result.errors)

    def test_no_agent_config_ok(self):
        spec = _minimal_valid_spec()
        del spec["agent_config"]
        result = validate_workflow_spec(spec)
        assert result.valid is True

    def test_duplicate_slot_ids(self):
        spec = _minimal_valid_spec()
        spec["required_slots"] = [
            {"slot_id": "dup", "type": "text", "question": "Q1"},
        ]
        spec["optional_slots"] = [
            {"slot_id": "dup", "type": "text", "question": "Q2"},
        ]
        result = validate_workflow_spec(spec)
        assert any("Duplicate slot_id" in e for e in result.errors)

    def test_unique_slot_ids(self):
        spec = _minimal_valid_spec()
        spec["optional_slots"] = [
            {"slot_id": "s1", "type": "text", "question": "Q1"},
            {"slot_id": "s2", "type": "text", "question": "Q2"},
        ]
        result = validate_workflow_spec(spec)
        assert result.valid is True

    def test_duplicate_preflight_rule_ids(self):
        spec = _minimal_valid_spec()
        spec["preflight_rules"].append(
            {"rule_id": "r1", "check_type": "x", "params": {}, "error_message": "E"}
        )
        result = validate_workflow_spec(spec)
        assert any("Duplicate preflight rule_id" in e for e in result.errors)

    def test_no_output_specs_warning(self):
        spec = _minimal_valid_spec()
        spec["output_specs"] = []
        result = validate_workflow_spec(spec)
        assert any("No output_specs" in w for w in result.warnings)

    def test_multiple_missing_fields_early_return(self):
        result = validate_workflow_spec({})
        assert result.valid is False
        assert len(result.errors) >= 3


# ── validate_tool_coverage ──────────────────────────────────────


class TestValidateToolCoverage:
    def test_all_tools_found(self):
        server = _make_server("my-server", ("my_tool",))
        spec = _minimal_valid_spec()
        result = validate_tool_coverage(spec, [server])
        assert result.valid is True

    def test_missing_tool(self):
        server = _make_server("my-server", ("other_tool",))
        spec = _minimal_valid_spec()
        result = validate_tool_coverage(spec, [server])
        assert result.valid is False
        assert any("not found" in e for e in result.errors)

    def test_no_mcp_config_warning(self):
        spec = {"spec_id": "x", "name": "X", "version": "1.0.0"}
        result = validate_tool_coverage(spec, [])
        assert any("No mcp_config" in w for w in result.warnings)

    def test_missing_server_warning(self):
        server = _make_server("other-server", ("t",))
        spec = _minimal_valid_spec()
        result = validate_tool_coverage(spec, [server])
        # my-server not in provided servers → warning
        assert any("not in provided tool_servers" in w for w in result.warnings)

    def test_multiple_servers(self):
        s1 = _make_server("s1", ("t1",))
        s2 = _make_server("s2", ("t2",))
        spec = _minimal_valid_spec()
        spec["mcp_config"] = {
            "mcp_servers": ["s1", "s2"],
            "tools": ["s1:t1", "s2:t2"],
        }
        result = validate_tool_coverage(spec, [s1, s2])
        assert result.valid is True

    def test_empty_tool_servers(self):
        spec = _minimal_valid_spec()
        result = validate_tool_coverage(spec, [])
        assert result.valid is False
