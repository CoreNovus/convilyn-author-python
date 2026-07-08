"""Granular policy config models — internal building blocks.

These thirteen pydantic models capture the wire shape for the workflow
spec's three policy slots:

* ``task_policy``  — clarify / infer / stop condition vocabularies
* ``routing_policy`` — total-step cap, retry caps, fallback action
* ``qa_policy`` — slot emission, goal validation, tool pipeline,
  failure rubric

They are kept here as the *granular* surface. The public author-facing
SDK exposes five high-level knobs (see :mod:`convilyn_sdk.policies`)
that compose these models via a translator. Re-exported from
:mod:`convilyn_sdk.workflow_policies` for one-release back-compat.

All models set ``model_config = ConfigDict(extra="allow")`` so adding a
new optional field on the platform side does NOT force an SDK bump
(OCP); authoritative ``extra="forbid"`` validation lives platform-side.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Literal vocabularies ──────────────────────────────────────────────

ClarifyCondition = Literal[
    "missing_required_identifier",
    "ambiguous_permission_scope",
    "low_signal_user_input",
    "conflicting_inputs",
    "tool_failure_blocks_progress",
    "missing_required_artifact",
]

InferCondition = Literal[
    "low_risk_preference",
    "formatting_choice",
    "tone_choice",
    "ordering_choice_when_unambiguous",
]

StopCondition = Literal[
    "user_requests_disallowed_action",
    "tool_result_conflicts_with_policy",
    "irrecoverable_state",
    "compliance_violation_detected",
]

NoToolResultAction = Literal["ask_user", "answer_with_uncertainty", "fail_safe"]

FailureCategory = Literal[
    "tool",
    "understanding",
    "planning",
    "format",
    "data",
    "illegal-fallback",
    "over-questioning",
    "hallucination",
]

QaSlotType = Literal["file", "text", "multi_choice", "single_choice", "number", "date"]

FirstQuestionFormat = Literal["multi_choice", "single_choice", "file"]

QualityCheckType = Literal["absent", "present"]

StructuralCheckType = Literal["min_paragraphs", "min_lines", "min_words"]


# ── task_policy ───────────────────────────────────────────────────────


class TaskPolicyConfig(BaseModel):
    """Declarative contract for when the agent clarifies / infers / stops.

    All three fields default to empty lists so the policy is permissive
    by default — the agent's prose-driven behaviour stays in place
    until an operator explicitly populates a list.

    The three Literal vocabularies are disjoint by design; the platform
    validators enforce this at spec load. Intra-list duplicates are an
    authoring typo signal and the platform rejects them.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    must_clarify_when: list[ClarifyCondition] = Field(default_factory=list)
    may_infer_when: list[InferCondition] = Field(default_factory=list)
    must_stop_when: list[StopCondition] = Field(default_factory=list)


# ── routing_policy ────────────────────────────────────────────────────


class RetryPolicyConfig(BaseModel):
    """Per-error-class retry caps."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tool_error: int = Field(default=2, ge=0, le=10)
    validation_error: int = Field(default=1, ge=0, le=10)


class FallbackPolicyConfig(BaseModel):
    """What to do when the model emits text without a tool call."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    no_tool_result: NoToolResultAction = "fail_safe"


class RoutingPolicyConfig(BaseModel):
    """Top-level routing contract — max_steps / retry / fallback."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            "Total reason turns the agent may take before terminating. "
            "None falls back to ``agent_config.max_iterations``. The "
            "platform emits a soft UserWarning when this exceeds 100."
        ),
    )
    retry_policy: RetryPolicyConfig | None = None
    fallback: FallbackPolicyConfig | None = None


# ── qa_policy sub-blocks ──────────────────────────────────────────────


class TerminalFailurePolicyConfig(BaseModel):
    """How the agent surfaces a terminal tool failure as ``failure_reason``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    applicable_tools: list[str] = Field(default_factory=list)
    message_template: str = "{tool_name}: {error_verbatim}"


class SlotPolicyConfig(BaseModel):
    """Slot-emission policy for ``request_user_input``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    forbid_non_file: bool = False
    allowed_slot_types: list[QaSlotType] | None = None
    first_question_format: FirstQuestionFormat | None = None
    terminal_failure_policy: TerminalFailurePolicyConfig | None = None


class SectionConfig(BaseModel):
    """A required output section with synonym fallbacks."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    synonyms: list[str] = Field(default_factory=list)


class QualityCheckConfig(BaseModel):
    """A negative or positive pattern check on artifact text."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: QualityCheckType
    patterns: list[str]
    reason: str
    min_matches: int = Field(default=1, ge=1)


class StructuralCheckConfig(BaseModel):
    """A structural assertion on artifact text."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: StructuralCheckType
    count: int = Field(ge=0)


class GoalCriteriaConfig(BaseModel):
    """Per-spec goal validation criteria."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    description: str = ""
    required_sections: list[SectionConfig] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    min_length: int = Field(default=0, ge=0)
    quality_checks: list[QualityCheckConfig] = Field(default_factory=list)
    structural_checks: list[StructuralCheckConfig] = Field(default_factory=list)


class ToolStageConfig(BaseModel):
    """A node in the expected tool pipeline (state-machine hint)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    allowed_after: list[str] = Field(default_factory=list)
    required: bool = True


class FailureRuleConfig(BaseModel):
    """A per-spec failure-classification rule."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    error_code_pattern: str
    log_pattern: str | None = None
    category: FailureCategory
    rationale_template: str


class QaPolicyConfig(BaseModel):
    """Per-spec QA policy block."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    slot_policy: SlotPolicyConfig | None = None
    goal_criteria: GoalCriteriaConfig | None = None
    tool_pipeline: list[ToolStageConfig] | None = None
    failure_rubric: list[FailureRuleConfig] | None = None


# ── Normaliser helper ─────────────────────────────────────────────────


def _coerce_to_model(value: Any, model: type[BaseModel]) -> Any:
    """Convert a dict (or already-typed instance) into the typed model.

    Used by the builder to let authors pass either typed configs or
    raw mappings without ceremony. Returns ``None`` unchanged so
    optional fields stay optional.
    """
    if value is None or isinstance(value, model):
        return value
    return model.model_validate(value)
