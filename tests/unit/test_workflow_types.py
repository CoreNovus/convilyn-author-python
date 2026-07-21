"""Tests for workflow_types Pydantic models — field validation and serialization."""

import pytest
from pydantic import ValidationError

from convilyn_author.workflow_types import (
    AgentConfigModel,
    InputConfig,
    LocalePolicyConfig,
    MCPConfigModel,
    OutputSpecConfig,
    PhaseConfig,
    PreflightRuleConfig,
    SlotConfig,
    WorkflowBlueprint,
)


class TestInputConfig:
    def test_defaults(self):
        cfg = InputConfig()
        assert cfg.types == []
        assert cfg.formats is None
        assert cfg.max_size_bytes is None
        assert cfg.min_file_count is None

    def test_all_fields(self):
        cfg = InputConfig(
            types=["document"],
            formats=["pdf"],
            max_size_bytes=1000,
            max_duration_seconds=60,
            min_duration_seconds=5,
            min_file_count=2,
        )
        assert cfg.min_file_count == 2
        assert cfg.max_duration_seconds == 60

    def test_min_file_count_negative_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            InputConfig(min_file_count=-1)


class TestOutputSpecConfig:
    def test_required_format(self):
        o = OutputSpecConfig(format="json")
        assert o.format == "json"
        assert o.additional == {}

    def test_with_additional(self):
        o = OutputSpecConfig(format="txt", additional={"type": "letter"})
        assert o.additional["type"] == "letter"

    def test_missing_format_raises(self):
        with pytest.raises(ValidationError):
            OutputSpecConfig()


class TestPhaseConfig:
    def test_valid(self):
        p = PhaseConfig(phase="Extract", description="Extract text.")
        assert p.phase == "Extract"

    def test_missing_fields_raises(self):
        with pytest.raises(ValidationError):
            PhaseConfig(phase="X")


class TestSlotConfig:
    def test_valid_choice_slot(self):
        s = SlotConfig(
            slot_id="lang",
            type="choice",
            question="Select language",
            options=["en", "zh"],
            default="en",
        )
        assert s.slot_id == "lang"
        assert s.required is False

    def test_valid_text_slot(self):
        s = SlotConfig(slot_id="s1", type="text", question="Input?")
        assert s.hidden is False

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            SlotConfig(slot_id="s1", type="invalid_type", question="Q?")

    def test_all_slot_types_accepted(self):
        for t in ["choice", "multi_choice", "text", "number", "boolean", "file", "date"]:
            s = SlotConfig(slot_id=f"s_{t}", type=t, question="Q?")
            assert s.type == t

    def test_with_depends_on(self):
        s = SlotConfig(
            slot_id="s1",
            type="text",
            question="Q?",
            depends_on={"slot": "enable", "equals": True},
        )
        assert s.depends_on["slot"] == "enable"

    def test_required_slot(self):
        s = SlotConfig(slot_id="r", type="text", question="Q?", required=True)
        assert s.required is True

    def test_hidden_slot(self):
        s = SlotConfig(slot_id="h", type="text", question="Q?", hidden=True)
        assert s.hidden is True

    def test_with_validation_rules(self):
        s = SlotConfig(
            slot_id="v",
            type="number",
            question="Q?",
            validation={"min": 0, "max": 100},
        )
        assert s.validation["max"] == 100


class TestPreflightRuleConfig:
    def test_valid(self):
        r = PreflightRuleConfig(
            rule_id="r1",
            check_type="file_count",
            params={"min": 1},
            error_message="Need file",
        )
        assert r.is_blocking is True
        assert r.description == ""

    def test_non_blocking(self):
        r = PreflightRuleConfig(
            rule_id="r2",
            check_type="file_format",
            params={},
            error_message="Wrong format",
            is_blocking=False,
        )
        assert r.is_blocking is False

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            PreflightRuleConfig(rule_id="r3")


class TestAgentConfigModel:
    def test_defaults(self):
        ac = AgentConfigModel()
        assert ac.system_prompt is None
        assert ac.max_iterations == 25
        assert ac.temperature == 0.3
        # Prompt-template id + engine-tuning knobs are NOT public.
        assert not hasattr(ac, "system_prompt_id")
        assert not hasattr(ac, "min_tools_for_auto")
        assert not hasattr(ac, "tool_progress_milestones")

    def test_custom_values(self):
        ac = AgentConfigModel(
            system_prompt="Custom",
            max_iterations=10,
            temperature=0.8,
        )
        assert ac.system_prompt == "Custom"
        assert ac.max_iterations == 10

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            AgentConfigModel(temperature=1.5)
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            AgentConfigModel(temperature=-0.1)

    def test_max_iterations_out_of_range(self):
        with pytest.raises(ValidationError):
            AgentConfigModel(max_iterations=0)
        with pytest.raises(ValidationError):
            AgentConfigModel(max_iterations=51)


class TestMCPConfigModel:
    def test_defaults(self):
        m = MCPConfigModel()
        assert m.mcp_servers == []
        assert m.tools == []

    def test_with_values(self):
        m = MCPConfigModel(mcp_servers=["s1"], tools=["s1:t1", "s1:t2"])
        assert len(m.tools) == 2


class TestLocalePolicyConfig:
    def test_defaults(self):
        lp = LocalePolicyConfig()
        assert lp.type == "locale_independent"
        assert lp.locale_market_map is None
        assert lp.affected_slots == []
        assert lp.prompt_hint is None

    def test_locale_bound(self):
        lp = LocalePolicyConfig(
            type="locale_bound",
            locale_market_map={"en": "us"},
            affected_slots=["region"],
            prompt_hint="Use {locale}",
        )
        assert lp.type == "locale_bound"
        assert lp.prompt_hint == "Use {locale}"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            LocalePolicyConfig(type="invalid")


class TestWorkflowBlueprint:
    def test_minimal(self):
        s = WorkflowBlueprint(spec_id="x", version="1.0.0", name="X")
        assert s.public_schema_version == "1"
        # Platform-internal fields are not part of the public blueprint.
        assert not hasattr(s, "category")
        assert not hasattr(s, "status")
        assert not hasattr(s, "sku_group")

    def test_full(self):
        s = WorkflowBlueprint(
            spec_id="test",
            version="2.0.0",
            name="Test",
            description="Desc",
            supported_input_types=["document"],
            output_specs=[OutputSpecConfig(format="txt")],
            phases=[PhaseConfig(phase="P1", description="D")],
            agent_config=AgentConfigModel(max_iterations=10),
            mcp_config=MCPConfigModel(tools=["s:t"]),
        )
        assert len(s.output_specs) == 1
        assert s.agent_config.max_iterations == 10

    def test_serialization(self):
        s = WorkflowBlueprint(spec_id="x", version="1.0.0", name="X")
        data = s.model_dump(exclude_none=True)
        assert "spec_id" in data
        assert "description" not in data  # None excluded

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            WorkflowBlueprint(spec_id="x", version="1.0.0")
