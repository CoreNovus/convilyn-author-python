"""Pydantic-level tests for the advanced types — logic / boundary / error / object-state.

Validates the wire shape of :class:`MultiRoleConfig`,
:class:`RoleConfig`, and :class:`CheckpointConfig` in
isolation from the builder. The builder-level integration tests live
in :mod:`tests.test_workflow_multi_agent` and
:mod:`tests.test_workflow_checkpoint`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from convilyn_author import CheckpointConfig, MultiRoleConfig, RoleConfig
from convilyn_author.workflow_types import SlotConfig

# ── 1. Logic — happy path round-trip ────────────────────────────────


class TestMultiRoleConfigLogic:
    def test_minimal_construction(self) -> None:
        config = MultiRoleConfig(active_specialists=["data_engineer"])
        assert config.active_specialists == ["data_engineer"]
        assert config.specialists is None
        assert config.autonomy_level == "require_verification"
        assert config.max_total_tool_calls == 100
        assert config.max_role_visits == 3

    def test_full_construction_round_trips(self) -> None:
        config = MultiRoleConfig(
            active_specialists=["data_engineer", "qa_analyst"],
            specialists={
                "data_engineer": RoleConfig(tools=["doc-parser:extract"]),
                "qa_analyst": RoleConfig(tools=["qa:check"]),
            },
            workflow_context={"locale_hints": ["en"]},
            rule_bundle_ref="finance/v1",
            rule_bundle_version="1.0.0",
            autonomy_level="autonomous",
            max_total_tool_calls=50,
            max_role_visits=2,
        )
        round_tripped = MultiRoleConfig.model_validate(config.model_dump(exclude_none=True))
        assert round_tripped.active_specialists == config.active_specialists
        assert round_tripped.autonomy_level == "autonomous"


class TestCheckpointConfigLogic:
    def test_minimal_construction(self) -> None:
        slot = SlotConfig(slot_id="topic", type="text", question="What topic?")
        cp = CheckpointConfig(
            after_phase="analyze",
            reason="need disambiguation",
            slots=[slot],
        )
        assert cp.after_phase == "analyze"
        assert len(cp.slots) == 1
        assert cp.slots[0].slot_id == "topic"


# ── 2. Boundary — empty lists, length caps, OCP (extra="allow") ─────


class TestMultiRoleConfigBoundary:
    def test_empty_active_specialists_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MultiRoleConfig(active_specialists=[])

    def test_max_total_tool_calls_upper_bound(self) -> None:
        # 10_000 is the documented cap; just over rejects.
        MultiRoleConfig(active_specialists=["a"], max_total_tool_calls=10_000)
        with pytest.raises(ValidationError):
            MultiRoleConfig(active_specialists=["a"], max_total_tool_calls=10_001)

    def test_max_role_visits_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            MultiRoleConfig(active_specialists=["a"], max_role_visits=0)

    def test_forward_compat_extra_field_accepted(self) -> None:
        """OCP: backend can add fields without an SDK bump."""
        config = MultiRoleConfig.model_validate(
            {
                "active_specialists": ["data_engineer"],
                "future_unknown_field": {"foo": "bar"},
            }
        )
        # `extra="allow"` keeps the unknown field on the instance for
        # round-trip; SDK doesn't expose a typed accessor.
        round_tripped = config.model_dump(exclude_none=True)
        assert round_tripped["future_unknown_field"] == {"foo": "bar"}


class TestRoleConfigBoundary:
    def test_tools_min_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RoleConfig(tools=[])

    def test_tools_max_length_enforced(self) -> None:
        RoleConfig(tools=[f"srv:t{i}" for i in range(64)])
        with pytest.raises(ValidationError):
            RoleConfig(tools=[f"srv:t{i}" for i in range(65)])


class TestCheckpointConfigBoundary:
    def test_empty_slots_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CheckpointConfig(after_phase="analyze", reason="x", slots=[])

    def test_missing_after_phase_rejected(self) -> None:
        slot = SlotConfig(slot_id="x", type="text", question="?")
        with pytest.raises(ValidationError):
            CheckpointConfig(reason="x", slots=[slot])  # type: ignore[call-arg]


# ── 3. Error — invalid Literal values, type mismatches ──────────────


class TestAutonomyLevelLiteral:
    def test_unknown_autonomy_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MultiRoleConfig(
                active_specialists=["a"],
                autonomy_level="full_yolo",  # type: ignore[arg-type]
            )

    def test_known_autonomy_levels_accepted(self) -> None:
        for level in ("autonomous", "require_verification"):
            MultiRoleConfig(active_specialists=["a"], autonomy_level=level)


# ── 4. Object-state — exclude_none behaviour, dict round-trip ───────


class TestExcludeNoneBehaviour:
    def test_unset_optionals_dropped(self) -> None:
        config = MultiRoleConfig(active_specialists=["a"])
        dumped = config.model_dump(exclude_none=True)
        assert "specialists" not in dumped
        assert "workflow_context" not in dumped
        assert dumped["active_specialists"] == ["a"]

    def test_explicit_none_specialists_drops_from_dump(self) -> None:
        config = MultiRoleConfig(active_specialists=["a"], specialists=None)
        dumped = config.model_dump(exclude_none=True)
        assert "specialists" not in dumped

    def test_explicit_specialists_kept_in_dump(self) -> None:
        config = MultiRoleConfig(
            active_specialists=["a"],
            specialists={"a": RoleConfig(tools=["srv:t1"])},
        )
        dumped = config.model_dump(exclude_none=True)
        assert dumped["specialists"]["a"]["tools"] == ["srv:t1"]
