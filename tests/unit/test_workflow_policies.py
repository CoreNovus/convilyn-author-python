"""4-category tests for the R3 HIGH policy blocks — task / routing / qa.

Covers both the Pydantic models and the builder fluent methods.
Mirrors the structure of :mod:`tests.test_workflow_advanced_types`
(PR-2) so each new policy type gets logic / boundary / error /
object-state coverage.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from convilyn_author import WorkflowSpec

# The granular ``*Config`` wire models are the advanced, non-SemVer surface;
# since the 2.0.0 major they live under ``convilyn_author.workflow_policies`` rather
# than at the package root (see docs/STABILITY.md + tests/contract).
from convilyn_author.workflow_policies import (
    FallbackPolicyConfig,
    GoalCriteriaConfig,
    QaPolicyConfig,
    QualityCheckConfig,
    RetryPolicyConfig,
    SlotPolicyConfig,
    TaskPolicyConfig,
)
from convilyn_author.workflow_validator import validate_workflow_spec


def _make_spec() -> WorkflowSpec:
    return (
        WorkflowSpec("policy_test", name="Policy Test")
        .with_input(types=["document"])
        .with_output(format="json")
        .add_phase("analyze", "Analyze the input.")
    )


# ── 1. TaskPolicy ───────────────────────────────────────────────────


class TestTaskPolicyLogic:
    def test_default_empty_lists(self) -> None:
        config = TaskPolicyConfig()
        assert config.must_clarify_when == []
        assert config.may_infer_when == []
        assert config.must_stop_when == []

    def test_builder_round_trips_via_compile(self) -> None:
        spec = _make_spec().with_task_policy(
            must_clarify_when=["missing_required_identifier", "conflicting_inputs"],
            may_infer_when=["formatting_choice"],
            must_stop_when=["compliance_violation_detected"],
        )
        compiled = spec.compile()
        tp = compiled["task_policy"]
        assert tp["must_clarify_when"] == [
            "missing_required_identifier",
            "conflicting_inputs",
        ]
        assert tp["may_infer_when"] == ["formatting_choice"]
        assert tp["must_stop_when"] == ["compliance_violation_detected"]


class TestTaskPolicyBoundary:
    def test_empty_invocation_emits_block_with_empty_lists(self) -> None:
        spec = _make_spec().with_task_policy()
        compiled = spec.compile()
        assert "task_policy" in compiled
        assert compiled["task_policy"]["must_clarify_when"] == []

    def test_immutability_preserves_original(self) -> None:
        base = _make_spec()
        with_tp = base.with_task_policy(must_clarify_when=["conflicting_inputs"])
        assert base._task_policy is None
        assert with_tp._task_policy is not None


class TestTaskPolicyErrors:
    def test_unknown_clarify_condition_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskPolicyConfig(must_clarify_when=["not_a_real_condition"])  # type: ignore[list-item]

    def test_cross_list_value_rejected_by_pydantic(self) -> None:
        """Disjoint-by-design: a ClarifyCondition can't sit in may_infer_when."""
        with pytest.raises(ValidationError):
            TaskPolicyConfig(may_infer_when=["missing_required_identifier"])  # type: ignore[list-item]


class TestTaskPolicyObjectState:
    def test_round_trip_via_from_dict(self) -> None:
        spec = _make_spec().with_task_policy(must_stop_when=["irrecoverable_state"])
        compiled = spec.compile()
        loaded = WorkflowSpec._from_dict(compiled)
        assert loaded.compile()["task_policy"] == compiled["task_policy"]


# ── 2. RoutingPolicy ────────────────────────────────────────────────


class TestRoutingPolicyLogic:
    def test_minimal_max_steps_only(self) -> None:
        spec = _make_spec().with_routing(max_steps=30)
        compiled = spec.compile()
        assert compiled["routing"]["max_steps"] == 30
        assert "retry_policy" not in compiled["routing"]

    def test_full_routing_block(self) -> None:
        spec = _make_spec().with_routing(
            max_steps=50,
            retry_policy=RetryPolicyConfig(tool_error=5, validation_error=2),
            fallback=FallbackPolicyConfig(no_tool_result="ask_user"),
        )
        rt = spec.compile()["routing"]
        assert rt["max_steps"] == 50
        assert rt["retry_policy"]["tool_error"] == 5
        assert rt["fallback"]["no_tool_result"] == "ask_user"

    def test_dict_inputs_coerced(self) -> None:
        spec = _make_spec().with_routing(
            max_steps=10,
            retry_policy={"tool_error": 3},
            fallback={"no_tool_result": "fail_safe"},
        )
        rt = spec.compile()["routing"]
        assert rt["retry_policy"]["tool_error"] == 3


class TestRoutingPolicyBoundary:
    def test_max_steps_upper_bound_200(self) -> None:
        spec = _make_spec().with_routing(max_steps=200)
        assert spec.compile()["routing"]["max_steps"] == 200

    def test_max_steps_above_200_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_spec().with_routing(max_steps=201)

    def test_retry_caps_le_10(self) -> None:
        with pytest.raises(ValidationError):
            _make_spec().with_routing(retry_policy={"tool_error": 11})

    def test_validator_warns_when_max_steps_above_100(self) -> None:
        spec = _make_spec().with_routing(max_steps=150)
        result = validate_workflow_spec(spec.compile())
        assert result.valid is True
        assert any("100-step advisory" in w for w in result.warnings)


class TestRoutingPolicyErrors:
    def test_unknown_no_tool_result_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FallbackPolicyConfig(no_tool_result="explode")  # type: ignore[arg-type]


class TestRoutingPolicyObjectState:
    def test_round_trip_via_from_dict(self) -> None:
        spec = _make_spec().with_routing(
            max_steps=20,
            fallback=FallbackPolicyConfig(no_tool_result="answer_with_uncertainty"),
        )
        compiled = spec.compile()
        loaded = WorkflowSpec._from_dict(compiled)
        assert loaded.compile()["routing"] == compiled["routing"]


# ── 3. QaPolicy ─────────────────────────────────────────────────────


class TestQaPolicyLogic:
    def test_slot_policy_only(self) -> None:
        spec = _make_spec().with_qa_policy(
            slot_policy=SlotPolicyConfig(forbid_non_file=True),
        )
        qa = spec.compile()["qa_policy"]
        assert qa["slot_policy"]["forbid_non_file"] is True

    def test_goal_criteria_with_required_sections(self) -> None:
        spec = _make_spec().with_qa_policy(
            goal_criteria=GoalCriteriaConfig(
                description="resume must include summary",
                required_sections=[{"name": "Summary"}],
                min_length=100,
            ),
        )
        gc = spec.compile()["qa_policy"]["goal_criteria"]
        assert gc["min_length"] == 100
        assert gc["required_sections"][0]["name"] == "Summary"

    def test_full_qa_policy_with_pipeline_and_rubric(self) -> None:
        spec = _make_spec().with_qa_policy(
            tool_pipeline=[
                {"name": "extract", "required": True},
                {"name": "summarize", "allowed_after": ["extract"]},
            ],
            failure_rubric=[
                {
                    "error_code_pattern": "TIMEOUT_.*",
                    "category": "tool",
                    "rationale_template": "Timeout on {tool_name}",
                },
            ],
        )
        qa = spec.compile()["qa_policy"]
        assert len(qa["tool_pipeline"]) == 2
        assert qa["failure_rubric"][0]["category"] == "tool"


class TestQaPolicyBoundary:
    def test_quality_check_min_matches_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            QualityCheckConfig(
                type="present",
                patterns=["foo"],
                reason="r",
                min_matches=0,
            )

    def test_structural_check_negative_count_rejected(self) -> None:
        from convilyn_author.workflow_policies import StructuralCheckConfig

        with pytest.raises(ValidationError):
            StructuralCheckConfig(type="min_paragraphs", count=-1)


class TestQaPolicyErrors:
    def test_unknown_failure_category_rejected(self) -> None:
        spec = _make_spec()
        with pytest.raises(ValidationError):
            spec.with_qa_policy(
                failure_rubric=[
                    {
                        "error_code_pattern": ".*",
                        "category": "fictional_category",
                        "rationale_template": "r",
                    }
                ],
            )

    def test_unknown_slot_type_in_allowlist_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SlotPolicyConfig(allowed_slot_types=["docx"])  # type: ignore[list-item]


class TestQaPolicyObjectState:
    def test_round_trip_via_from_dict(self) -> None:
        spec = _make_spec().with_qa_policy(
            slot_policy=SlotPolicyConfig(
                forbid_non_file=True,
                allowed_slot_types=["file"],
                first_question_format="file",
            ),
        )
        compiled = spec.compile()
        loaded = WorkflowSpec._from_dict(compiled)
        assert loaded.compile()["qa_policy"] == compiled["qa_policy"]

    def test_extra_field_round_trips_via_extra_allow(self) -> None:
        """OCP: a forward-compat field added by the backend round-trips."""
        config = QaPolicyConfig.model_validate(
            {"slot_policy": {"forbid_non_file": True}, "future_field": "x"}
        )
        dumped = config.model_dump(exclude_none=True)
        assert dumped["future_field"] == "x"


# ── 4. Integration — all three policies on one spec ─────────────────


class TestAllThreePoliciesTogether:
    def test_combined_compile(self) -> None:
        spec = (
            _make_spec()
            .with_task_policy(must_clarify_when=["missing_required_identifier"])
            .with_routing(max_steps=10)
            .with_qa_policy(slot_policy=SlotPolicyConfig(forbid_non_file=True))
        )
        compiled = spec.compile()
        assert "task_policy" in compiled
        assert "routing" in compiled
        assert "qa_policy" in compiled

    def test_no_warning_when_max_steps_at_or_below_threshold(self) -> None:
        spec = _make_spec().with_routing(max_steps=100)
        # Compile path: no UserWarning at threshold.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            spec.compile()
        relevant = [w for w in caught if "max_steps" in str(w.message)]
        assert relevant == []
