"""Tests for the five high-level policy knobs + the translator.

Covers, per policy: a logic happy path, a boundary case, an error case,
and the translator's wire-block output. A final integration block
asserts the builder's ``with_policy(...)`` composes multiple knobs
deterministically and rejects overlapping kinds.
"""

from __future__ import annotations

import pytest

from convilyn_author import (
    FailureRule,
    FallbackPolicy,
    HumanReviewPolicy,
    OutputValidationPolicy,
    PatternCheck,
    RequiredSection,
    RetryPolicy,
    StructureCheck,
    TerminalFailureRule,
    TimeoutPolicy,
    ToolStage,
    WorkflowSpec,
)
from convilyn_author._internal.policy_translator import (
    apply_policies,
    merge_wire_blocks,
)


def _make_spec() -> WorkflowSpec:
    return (
        WorkflowSpec("policy_test", name="Policy Test")
        .with_input(types=["document"])
        .with_output(format="json")
        .add_phase("analyze", "First phase.")
    )


# ── RetryPolicy ────────────────────────────────────────────────────────


class TestRetryPolicy:
    def test_defaults_emit_minimal_wire(self) -> None:
        wire = RetryPolicy().to_wire()
        assert wire == {
            "routing_policy": {
                "retry_policy": {"tool_error": 2, "validation_error": 1},
            },
        }

    def test_terminal_failure_writes_qa_slot_policy(self) -> None:
        wire = RetryPolicy(
            terminal_failure=TerminalFailureRule(applicable_tools=["doc:parse"]),
        ).to_wire()
        tf = wire["qa_policy"]["slot_policy"]["terminal_failure_policy"]
        assert tf["applicable_tools"] == ["doc:parse"]

    def test_classify_failures_emits_failure_rubric(self) -> None:
        wire = RetryPolicy(
            classify_failures=[
                FailureRule(
                    error_code_pattern="^TOOL_",
                    category="tool",
                    rationale_template="tool failed",
                ),
            ],
        ).to_wire()
        rubric = wire["qa_policy"]["failure_rubric"]
        assert rubric[0]["error_code_pattern"] == "^TOOL_"
        assert rubric[0]["category"] == "tool"

    def test_retry_cap_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(tool_error=11)


# ── TimeoutPolicy ──────────────────────────────────────────────────────


class TestTimeoutPolicy:
    def test_default_emits_empty(self) -> None:
        assert TimeoutPolicy().to_wire() == {}

    def test_max_total_steps_writes_routing(self) -> None:
        wire = TimeoutPolicy(max_total_steps=50).to_wire()
        assert wire == {"routing_policy": {"max_steps": 50}}

    def test_tool_pipeline_writes_qa(self) -> None:
        wire = TimeoutPolicy(
            tool_pipeline=[
                ToolStage(name="extract", required=True),
                ToolStage(name="review", allowed_after=["extract"]),
            ],
        ).to_wire()
        pipeline = wire["qa_policy"]["tool_pipeline"]
        assert pipeline[0]["name"] == "extract"
        assert pipeline[1]["allowed_after"] == ["extract"]

    def test_max_steps_upper_bound_enforced(self) -> None:
        with pytest.raises(ValueError):
            TimeoutPolicy(max_total_steps=201)


# ── OutputValidationPolicy ─────────────────────────────────────────────


class TestOutputValidationPolicy:
    def test_default_emits_empty_goal_criteria(self) -> None:
        wire = OutputValidationPolicy().to_wire()
        gc = wire["qa_policy"]["goal_criteria"]
        assert gc["description"] == ""
        assert gc["required_sections"] == []
        assert gc["anti_patterns"] == []
        assert gc["min_length"] == 0
        assert gc["quality_checks"] == []
        assert gc["structural_checks"] == []

    def test_required_sections_and_patterns_compose(self) -> None:
        wire = OutputValidationPolicy(
            description="invoice review",
            required_sections=[RequiredSection(name="summary", synonyms=["TLDR"])],
            anti_patterns=["TODO"],
            min_length=200,
            pattern_checks=[
                PatternCheck(
                    type="present",
                    patterns=["amount: "],
                    reason="invoice must show amount",
                ),
            ],
            structure_checks=[StructureCheck(type="min_paragraphs", count=3)],
        ).to_wire()
        gc = wire["qa_policy"]["goal_criteria"]
        assert gc["description"] == "invoice review"
        assert gc["required_sections"][0]["name"] == "summary"
        assert gc["anti_patterns"] == ["TODO"]
        assert gc["min_length"] == 200
        assert gc["quality_checks"][0]["patterns"] == ["amount: "]
        assert gc["structural_checks"][0]["type"] == "min_paragraphs"

    def test_negative_min_length_rejected(self) -> None:
        with pytest.raises(ValueError):
            OutputValidationPolicy(min_length=-1)


# ── HumanReviewPolicy ──────────────────────────────────────────────────


class TestHumanReviewPolicy:
    def test_default_emits_minimal(self) -> None:
        wire = HumanReviewPolicy().to_wire()
        assert wire == {"qa_policy": {"slot_policy": {"forbid_non_file": False}}}

    def test_files_only_and_allowlist_compose(self) -> None:
        wire = HumanReviewPolicy(
            files_only=True,
            allowed_slot_types=["file", "text"],
            first_question_format="file",
        ).to_wire()
        sp = wire["qa_policy"]["slot_policy"]
        assert sp["forbid_non_file"] is True
        assert sp["allowed_slot_types"] == ["file", "text"]
        assert sp["first_question_format"] == "file"


# ── FallbackPolicy ─────────────────────────────────────────────────────


class TestFallbackPolicy:
    def test_default_emits_default_action(self) -> None:
        wire = FallbackPolicy().to_wire()
        assert wire == {
            "task_policy": {
                "must_clarify_when": [],
                "may_infer_when": [],
                "must_stop_when": [],
            },
            "routing_policy": {"fallback": {"no_tool_result": "fail_safe"}},
        }

    def test_conditions_and_action_compose(self) -> None:
        wire = FallbackPolicy(
            must_clarify_when=["conflicting_inputs"],
            may_infer_when=["formatting_choice"],
            must_stop_when=["irrecoverable_state"],
            on_no_tool_result="ask_user",
        ).to_wire()
        tp = wire["task_policy"]
        assert tp["must_clarify_when"] == ["conflicting_inputs"]
        assert tp["may_infer_when"] == ["formatting_choice"]
        assert tp["must_stop_when"] == ["irrecoverable_state"]
        rp = wire["routing_policy"]
        assert rp["fallback"]["no_tool_result"] == "ask_user"


# ── Translator ─────────────────────────────────────────────────────────


class TestTranslator:
    def test_merge_wire_blocks_deep(self) -> None:
        base = {"routing_policy": {"retry_policy": {"tool_error": 2}}}
        addition = {"routing_policy": {"fallback": {"no_tool_result": "ask_user"}}}
        merged = merge_wire_blocks(base, addition)
        assert merged == {
            "routing_policy": {
                "retry_policy": {"tool_error": 2},
                "fallback": {"no_tool_result": "ask_user"},
            },
        }

    def test_merge_wire_blocks_conflict_raises(self) -> None:
        base = {"routing_policy": {"max_steps": 10}}
        addition = {"routing_policy": {"max_steps": 20}}
        with pytest.raises(ValueError, match="Policy conflict"):
            merge_wire_blocks(base, addition)

    def test_apply_rejects_duplicate_kinds(self) -> None:
        with pytest.raises(ValueError, match="Duplicate policy kind"):
            apply_policies([RetryPolicy(), RetryPolicy()])

    def test_apply_composes_disjoint_policies(self) -> None:
        out = apply_policies(
            [
                RetryPolicy(tool_error=3),
                FallbackPolicy(on_no_tool_result="ask_user"),
                TimeoutPolicy(max_total_steps=20),
            ],
        )
        assert out["routing_policy"]["retry_policy"]["tool_error"] == 3
        assert out["routing_policy"]["fallback"]["no_tool_result"] == "ask_user"
        assert out["routing_policy"]["max_steps"] == 20


# ── Builder integration ───────────────────────────────────────────────


class TestWithPolicy:
    def test_with_policy_writes_into_internal_slots(self) -> None:
        spec = _make_spec().with_policy(
            RetryPolicy(tool_error=4),
            TimeoutPolicy(max_total_steps=30),
        )
        compiled = spec.compile()
        assert compiled["routing"]["retry_policy"]["tool_error"] == 4
        assert compiled["routing"]["max_steps"] == 30

    def test_with_policy_composes_with_granular(self) -> None:
        spec = (
            _make_spec()
            .with_task_policy(must_stop_when=["irrecoverable_state"])
            .with_policy(RetryPolicy(tool_error=5))
        )
        compiled = spec.compile()
        assert compiled["task_policy"]["must_stop_when"] == ["irrecoverable_state"]
        assert compiled["routing"]["retry_policy"]["tool_error"] == 5

    def test_with_policy_rejects_duplicate_kind(self) -> None:
        with pytest.raises(ValueError):
            _make_spec().with_policy(RetryPolicy(), RetryPolicy())

    def test_with_policy_chains_immutably(self) -> None:
        base = _make_spec()
        with_p = base.with_policy(RetryPolicy(tool_error=4))
        assert base._task_policy is None
        assert base._routing is None
        assert with_p._routing is not None
        assert with_p._routing.retry_policy is not None
        assert with_p._routing.retry_policy.tool_error == 4
