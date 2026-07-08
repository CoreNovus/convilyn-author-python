"""Five high-level policy knobs — the author-facing surface.

The SDK exposes five composable policies an author can apply to a
:class:`~convilyn_sdk.WorkflowSpec`:

* :class:`RetryPolicy` — per-error-class retry caps + terminal-failure
  messaging.
* :class:`TimeoutPolicy` — overall step cap + (optional) tool pipeline
  staging.
* :class:`OutputValidationPolicy` — what the artifact must contain
  (required sections, anti-patterns, length / structure / pattern
  checks).
* :class:`HumanReviewPolicy` — slot-emission behaviour during
  ``request_user_input``.
* :class:`FallbackPolicy` — what to do when the agent stalls or
  produces no tool call (clarify / infer / stop vocabularies + the
  no-tool-result action).

Each class conforms to :class:`PolicyProtocol` (``kind`` + ``to_wire()``),
so adding a sixth policy means writing one more class + one translator
entry — no builder method changes. The granular wire-shape models live
in :mod:`convilyn_sdk._internal.legacy_policies` and are composed by
the translator; authors should not normally need to touch them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from convilyn_sdk._internal.legacy_policies import (
    ClarifyCondition,
    FailureCategory,
    FailureRuleConfig,
    FallbackPolicyConfig,
    FirstQuestionFormat,
    GoalCriteriaConfig,
    InferCondition,
    NoToolResultAction,
    QaSlotType,
    QualityCheckConfig,
    QualityCheckType,
    RetryPolicyConfig,
    RoutingPolicyConfig,
    SectionConfig,
    SlotPolicyConfig,
    StopCondition,
    StructuralCheckConfig,
    StructuralCheckType,
    TaskPolicyConfig,
    TerminalFailurePolicyConfig,
    ToolStageConfig,
)

# ── RetryPolicy ───────────────────────────────────────────────────────


class TerminalFailureRule(BaseModel):
    """How a single tool's terminal failure surfaces to the user."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    applicable_tools: list[str] = Field(default_factory=list)
    message_template: str = "{tool_name}: {error_verbatim}"


class FailureRule(BaseModel):
    """Author-facing failure-classification rule."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    error_code_pattern: str
    log_pattern: str | None = None
    category: FailureCategory
    rationale_template: str


class RetryPolicy(BaseModel):
    """Per-error-class retry caps plus terminal-failure messaging.

    ``tool_error`` and ``validation_error`` cap retries on transient
    failures. ``terminal_failure`` controls how an unrecoverable failure
    is rendered for the user. ``classify_failures`` lists rules that map
    error codes / log signatures into the eight-category failure
    taxonomy the platform reports back.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["retry"] = "retry"
    tool_error: int = Field(default=2, ge=0, le=10)
    validation_error: int = Field(default=1, ge=0, le=10)
    terminal_failure: TerminalFailureRule | None = None
    classify_failures: list[FailureRule] = Field(default_factory=list)

    def to_wire(self) -> dict[str, dict]:
        out: dict[str, dict] = {
            "routing_policy": {
                "retry_policy": RetryPolicyConfig(
                    tool_error=self.tool_error,
                    validation_error=self.validation_error,
                ).model_dump(exclude_none=True),
            },
        }
        if self.terminal_failure is not None or self.classify_failures:
            qa: dict = {}
            if self.terminal_failure is not None:
                qa["slot_policy"] = {
                    "terminal_failure_policy": TerminalFailurePolicyConfig(
                        applicable_tools=list(self.terminal_failure.applicable_tools),
                        message_template=self.terminal_failure.message_template,
                    ).model_dump(exclude_none=True),
                }
            if self.classify_failures:
                qa["failure_rubric"] = [
                    FailureRuleConfig(
                        error_code_pattern=rule.error_code_pattern,
                        log_pattern=rule.log_pattern,
                        category=rule.category,
                        rationale_template=rule.rationale_template,
                    ).model_dump(exclude_none=True)
                    for rule in self.classify_failures
                ]
            out["qa_policy"] = qa
        return out


# ── TimeoutPolicy ─────────────────────────────────────────────────────


class ToolStage(BaseModel):
    """One node in an expected tool pipeline."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    allowed_after: list[str] = Field(default_factory=list)
    required: bool = True


class TimeoutPolicy(BaseModel):
    """Overall step cap plus an optional staged tool pipeline.

    ``max_total_steps`` bounds the total reason turns the agent may
    take. ``tool_pipeline`` (optional) names the tools and their legal
    transitions, letting the platform short-circuit obviously off-track
    runs without waiting for the cap.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["timeout"] = "timeout"
    max_total_steps: int | None = Field(default=None, ge=1, le=200)
    tool_pipeline: list[ToolStage] = Field(default_factory=list)

    def to_wire(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.max_total_steps is not None:
            out["routing_policy"] = {
                "max_steps": RoutingPolicyConfig(
                    max_steps=self.max_total_steps
                ).max_steps,
            }
        if self.tool_pipeline:
            out["qa_policy"] = {
                "tool_pipeline": [
                    ToolStageConfig(
                        name=stage.name,
                        allowed_after=list(stage.allowed_after),
                        required=stage.required,
                    ).model_dump(exclude_none=True)
                    for stage in self.tool_pipeline
                ],
            }
        return out


# ── OutputValidationPolicy ────────────────────────────────────────────


class RequiredSection(BaseModel):
    """One required output section with optional synonym fallbacks."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    synonyms: list[str] = Field(default_factory=list)


class PatternCheck(BaseModel):
    """A positive/negative pattern check on artifact text."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: QualityCheckType
    patterns: list[str]
    reason: str
    min_matches: int = Field(default=1, ge=1)


class StructureCheck(BaseModel):
    """A structural assertion on artifact text."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: StructuralCheckType
    count: int = Field(ge=0)


class OutputValidationPolicy(BaseModel):
    """What the final artifact must contain to be considered acceptable.

    All fields are independently optional; supplying a partial policy
    only constrains the listed dimensions and leaves the rest to the
    agent's default prose-driven behaviour.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["output_validation"] = "output_validation"
    description: str = ""
    required_sections: list[RequiredSection] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    min_length: int = Field(default=0, ge=0)
    pattern_checks: list[PatternCheck] = Field(default_factory=list)
    structure_checks: list[StructureCheck] = Field(default_factory=list)

    def to_wire(self) -> dict[str, dict]:
        criteria = GoalCriteriaConfig(
            description=self.description,
            required_sections=[
                SectionConfig(name=s.name, synonyms=list(s.synonyms))
                for s in self.required_sections
            ],
            anti_patterns=list(self.anti_patterns),
            min_length=self.min_length,
            quality_checks=[
                QualityCheckConfig(
                    type=pc.type,
                    patterns=list(pc.patterns),
                    reason=pc.reason,
                    min_matches=pc.min_matches,
                )
                for pc in self.pattern_checks
            ],
            structural_checks=[
                StructuralCheckConfig(type=sc.type, count=sc.count)
                for sc in self.structure_checks
            ],
        )
        return {"qa_policy": {"goal_criteria": criteria.model_dump(exclude_none=True)}}


# ── HumanReviewPolicy ─────────────────────────────────────────────────


class HumanReviewPolicy(BaseModel):
    """Slot-emission behaviour when the agent pauses for user input.

    ``files_only`` restricts slots to file uploads only (useful for
    workflows where every user-supplied input is a document).
    ``allowed_slot_types`` is the explicit per-workflow allowlist;
    ``first_question_format`` pins the shape of the very first prompt
    the user sees (helpful for guided onboarding flows).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["human_review"] = "human_review"
    files_only: bool = False
    allowed_slot_types: list[QaSlotType] = Field(default_factory=list)
    first_question_format: FirstQuestionFormat | None = None

    def to_wire(self) -> dict[str, dict]:
        slot = SlotPolicyConfig(
            forbid_non_file=self.files_only,
            allowed_slot_types=list(self.allowed_slot_types) or None,
            first_question_format=self.first_question_format,
        )
        return {"qa_policy": {"slot_policy": slot.model_dump(exclude_none=True)}}


# ── FallbackPolicy ────────────────────────────────────────────────────


class FallbackPolicy(BaseModel):
    """When the agent stalls — clarify / infer / stop vocabularies plus
    the no-tool-result action.

    The three condition lists are disjoint by design; populating one
    list does not affect the others. ``on_no_tool_result`` controls how
    the platform responds when the model emits text without a tool
    call — usually after the agent has exhausted its options.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["fallback"] = "fallback"
    must_clarify_when: list[ClarifyCondition] = Field(default_factory=list)
    may_infer_when: list[InferCondition] = Field(default_factory=list)
    must_stop_when: list[StopCondition] = Field(default_factory=list)
    on_no_tool_result: NoToolResultAction = "fail_safe"

    def to_wire(self) -> dict[str, dict]:
        return {
            "task_policy": TaskPolicyConfig(
                must_clarify_when=list(self.must_clarify_when),
                may_infer_when=list(self.may_infer_when),
                must_stop_when=list(self.must_stop_when),
            ).model_dump(exclude_none=True),
            "routing_policy": {
                "fallback": FallbackPolicyConfig(
                    no_tool_result=self.on_no_tool_result,
                ).model_dump(exclude_none=True),
            },
        }


__all__ = [
    "FailureRule",
    "FallbackPolicy",
    "HumanReviewPolicy",
    "OutputValidationPolicy",
    "PatternCheck",
    "RequiredSection",
    "RetryPolicy",
    "StructureCheck",
    "TerminalFailureRule",
    "TimeoutPolicy",
    "ToolStage",
]
