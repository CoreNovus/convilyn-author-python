"""Pydantic models for workflow specification validation.

These shape the wire JSON the SDK emits, providing SDK-side validation
before submission to the platform.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class InputConfig(BaseModel):
    """Input constraints for a workflow."""

    types: list[str] = Field(
        default_factory=list,
        description="Supported input types (document, image, video, audio)",
    )
    formats: list[str] | None = Field(
        None,
        description="Specific supported formats (pdf, docx, png, etc.)",
    )
    max_size_bytes: int | None = Field(
        None,
        description="Maximum input file size in bytes",
    )
    max_duration_seconds: int | None = Field(
        None,
        description="Maximum input duration for video/audio",
    )
    min_duration_seconds: int | None = Field(
        None,
        description="Minimum input duration for video/audio",
    )
    min_file_count: int | None = Field(
        None,
        ge=0,
        description="Minimum number of files required",
    )


class OutputSpecConfig(BaseModel):
    """Output format specification."""

    format: str = Field(..., description="Output format (txt, pdf, json, xlsx, etc.)")
    additional: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional format-specific settings",
    )


class PhaseConfig(BaseModel):
    """Workflow phase definition for agent instructions."""

    phase: str = Field(..., description="Phase name")
    description: str = Field(..., description="Detailed phase instructions for the agent")


class SlotConfig(BaseModel):
    """User input slot definition."""

    slot_id: str = Field(..., description="Unique slot identifier")
    type: Literal["choice", "multi_choice", "text", "number", "boolean", "file", "date"] = Field(
        ..., description="Slot input type"
    )
    question: str = Field(..., description="Question displayed to user")
    options: list[str | dict[str, str]] | None = Field(
        None, description="Options for choice/multi_choice types"
    )
    default: Any = Field(None, description="Default value")
    required: bool = Field(default=False, description="Whether slot must be filled")
    hidden: bool = Field(default=False, description="Auto-filled, not shown to user")
    i18n_key: str | None = Field(None, description="i18n key for question translation")
    validation: dict[str, Any] | None = Field(None, description="Validation rules")
    depends_on: dict[str, Any] | None = Field(
        None, description="Conditional display based on other slots"
    )


class PreflightRuleConfig(BaseModel):
    """Preflight validation rule run before job execution."""

    rule_id: str = Field(..., description="Unique rule identifier")
    description: str = Field(default="", description="Human-readable description")
    check_type: str = Field(
        ..., description="Check type (file_count, file_format, file_type, duration, etc.)"
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Check parameters")
    error_message: str = Field(..., description="Error message on failure")
    is_blocking: bool = Field(default=True, description="Whether failure blocks execution")


class AgentConfigModel(BaseModel):
    """Public agent-mode knobs an author may set on a blueprint.

    Deliberately minimal: the platform owns prompt-template selection and
    engine-tuning internals (those are NOT part of the public surface and
    are filled in by the server-side translator). Authors may supply their
    OWN ``system_prompt`` text override; they cannot name an internal
    prompt-template id.
    """

    system_prompt: str | None = Field(
        None,
        description="Optional custom system-prompt text supplied by the author",
    )
    max_iterations: int = Field(
        default=25,
        ge=1,
        le=50,
        description="Maximum agent loop iterations",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="LLM temperature",
    )


class MCPConfigModel(BaseModel):
    """MCP server and tool configuration."""

    mcp_servers: list[str] = Field(
        default_factory=list,
        description="List of required MCP server names",
    )
    tools: list[str] = Field(
        default_factory=list,
        max_length=20,
        description='Tool references in "server:tool" format',
    )


class LocalePolicyConfig(BaseModel):
    """Locale behavior policy."""

    type: Literal["locale_bound", "locale_independent"] = Field(
        default="locale_independent",
        description="Whether locale constrains content scope or only UI language",
    )
    locale_market_map: dict[str, str] | None = Field(
        None,
        description="Locale code → market name mapping",
    )
    affected_slots: list[str] = Field(
        default_factory=list,
        description="Slot IDs auto-adjusted by locale",
    )
    prompt_hint: str | None = Field(
        None,
        description="Template appended to LLM prompt for locale-bound workflows",
    )


#: Public blueprint schema version. The server-side translator is keyed
#: on this so the platform's executable contract can evolve without
#: breaking an already-published author SDK. Bump only on a breaking
#: blueprint change.
PUBLIC_SCHEMA_VERSION = "1"


class WorkflowBlueprint(BaseModel):
    """The public author-facing workflow definition.

    This is the only workflow shape the author SDK emits and submits — a
    deliberately focused subset of authoring intent. The platform
    translates it server-side into the executable form it runs; internal
    execution details are not part of this public surface, which keeps the
    contract stable while the runtime evolves independently.

    Fields here are author intent only: identity, i18n/discovery metadata,
    input/output constraints, slots, preflight rules, locale behaviour,
    phase *descriptions*, tool references, and high-level policy knobs.
    """

    public_schema_version: str = Field(
        default=PUBLIC_SCHEMA_VERSION,
        description="Version of the public blueprint schema (translator key)",
    )

    spec_id: str
    version: str
    name: str = Field(max_length=80)
    description: str | None = None
    description_i18n: dict[str, str] | None = None

    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    supported_input_types: list[str] = Field(default_factory=list)
    max_input_size_bytes: int | None = None
    max_input_duration_seconds: int | None = None
    min_input_duration_seconds: int | None = None
    supported_input_formats: list[str] | None = None

    output_specs: list[OutputSpecConfig] = Field(default_factory=list)

    required_slots: list[SlotConfig] = Field(default_factory=list)
    optional_slots: list[SlotConfig] = Field(default_factory=list)

    preflight_rules: list[PreflightRuleConfig] = Field(default_factory=list)

    # ``default_factory=LocalePolicyConfig`` is correct at runtime
    # (Pydantic invokes it with zero args; the model's fields all have
    # their own defaults), but pyright's ``Field`` overload demands a
    # strict ``() -> _T`` callable and sees LocalePolicyConfig's
    # generated ``__init__`` as taking required kwargs. Wrapping in a
    # lambda preserves runtime semantics + satisfies the static check.
    locale_policy: LocalePolicyConfig = Field(
        default_factory=lambda: LocalePolicyConfig(),  # pyright: ignore[reportCallIssue]
    )

    agent_config: AgentConfigModel | None = None
    mcp_config: MCPConfigModel | None = None
    phases: list[PhaseConfig] | None = None

    # High-level author policy knobs. Typed as opaque dicts here so this
    # model stays self-contained — structured Pydantic siblings live in
    # workflow_advanced_types and workflow_policies to avoid import cycles.
    # The builder serialises those author objects via ``model_dump`` before
    # assigning. The server-side translator owns mapping these into the
    # internal wire blocks; they are author *intent*, not the engine
    # contract.
    multi_agent: dict[str, Any] | None = None
    checkpoints: dict[str, dict[str, Any]] | None = None
    task_policy: dict[str, Any] | None = None
    routing: dict[str, Any] | None = None
    qa_policy: dict[str, Any] | None = None


# Back-compat alias — the old name referred to the same builder output.
# Kept so internal imports don't break mid-refactor; the public,
# documented name is ``WorkflowBlueprint``.
CompiledWorkflowSpec = WorkflowBlueprint
