"""Pydantic siblings for the fluent-builder advanced surface.

These models capture the wire shape of two optional workflow blocks the
builder exposes:

* ``multi_agent`` → :class:`MultiRoleConfig` (+ :class:`RoleConfig`)
* ``checkpoints``  → ``dict[str, :class:`CheckpointConfig`]`` (additive
  builder; each ``with_resume_boundary(...)`` adds one entry)

Kept in a dedicated module so the diff and the public surface stay
isolated from :mod:`workflow_types`.

OCP: every model sets ``extra="allow"`` so a server that adds a new
optional field does NOT force an SDK bump — authors round-trip the new
field via ``compile()`` → ``model_dump()`` without the SDK knowing
about it. The authoritative validation lives server-side; the SDK's
job is to give Pythonic typed authoring on the surface and stay
permissive on the wire.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from convilyn_author.workflow_types import SlotConfig

AutonomyLevel = Literal["autonomous", "require_verification"]


class RoleConfig(BaseModel):
    """Per-role execution policy (currently: tool allowlist only).

    Reused by :meth:`WorkflowSpec.with_multi_role` when an author
    passes a structured :class:`~convilyn_author.agent_role.AgentRole`
    (with a ``tool_allowlist``) instead of a bare role string.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tools: list[str] = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            'Canonical tool refs this role may invoke ("server:tool"). '
            "Must be a subset of the workflow's own mcp_config.tools; "
            "cross-field enforcement happens server-side at spec load."
        ),
    )


class MultiRoleConfig(BaseModel):
    """Top-level multi-role block — opts a workflow into multi-role mode.

    The ``active_specialists`` list is the *ordered* set of roles the
    workflow exposes; the runtime decides the order in which they are
    invoked.

    Authors set this via :meth:`WorkflowSpec.with_multi_role`; calling
    it twice on the same builder replaces the block (no implicit
    merging — explicit composition is the author's job).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    active_specialists: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered list of role identifiers exposed to the workflow.",
    )
    specialists: dict[str, RoleConfig] | None = Field(
        default=None,
        description=(
            "Per-role execution policies. Keys must match "
            "active_specialists exactly. When None, every role may "
            "invoke any tool the workflow declared."
        ),
    )
    workflow_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Frozen workflow-specific hints threaded into each role's "
            "task context. Permissive shape — keys are workflow-defined; "
            "roles read what they recognise."
        ),
    )
    rule_bundle_ref: str | None = Field(default=None, max_length=256)
    rule_bundle_version: str | None = Field(default=None, max_length=64)
    autonomy_level: AutonomyLevel = Field(
        default="require_verification",
        description=(
            "External-action gate. 'autonomous' unlocks tools that "
            "perform external writes; any other value keeps the gate "
            "closed and requires explicit user confirmation."
        ),
    )
    max_total_tool_calls: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Aggregate MCP tool-call cap across every role in one run.",
    )
    max_role_visits: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Per-role visit count cap. Kicks in for peer review or routing hints.",
    )


class CheckpointConfig(BaseModel):
    """One mid-execution pause point — emits ``slot_needed`` when hit.

    ``after_phase`` references a phase name added via
    :meth:`WorkflowSpec.add_phase`; ``slots`` reuses the existing
    :class:`SlotConfig` vocabulary because the same ``slot_needed`` event
    shape covers both up-front and mid-run slot collection.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    after_phase: str = Field(
        ...,
        description=(
            "Name of the phase after which this resume boundary fires. "
            "Must match one of the workflow's :meth:`add_phase` entries; "
            "the SDK validator emits a warning if it doesn't."
        ),
    )
    reason: str = Field(
        ...,
        description=(
            "Human-readable rationale displayed alongside the "
            "slot_needed event so users understand why execution paused."
        ),
    )
    slots: list[SlotConfig] = Field(
        ...,
        min_length=1,
        description="Slots the user must answer before execution resumes.",
    )
