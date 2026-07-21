"""Builder-level tests for ``WorkflowSpec.with_dynamic_slots`` (issue #2435).

Covers the additive, default-OFF opt-in that emits
``agent_config.allow_dynamic_slots = True`` on the compiled blueprint:
the happy-path emission, the byte-identical back-compat guarantee when
NOT opted in, immutability, composition with ``with_agent_config`` in
both orders, and round-trip parity via ``_from_dict``.
"""

from __future__ import annotations

import json

from convilyn_author import WorkflowSpec


def _make_spec() -> WorkflowSpec:
    return (
        WorkflowSpec("dyn_slots_test", name="Dynamic Slots Test")
        .with_input(types=["document"])
        .with_output(format="json")
        .add_phase("analyze", "First phase.")
    )


# ── 1. Logic — happy path ────────────────────────────────────────────


class TestWithDynamicSlotsLogic:
    def test_opt_in_sets_allow_dynamic_slots_true(self) -> None:
        # Arrange / Act
        compiled = _make_spec().with_dynamic_slots().compile()
        # Assert
        assert compiled["agent_config"]["allow_dynamic_slots"] is True

    def test_opt_in_without_agent_config_still_emits_flag(self) -> None:
        """Opting in works even if the author never called with_agent_config."""
        # Arrange / Act
        compiled = _make_spec().with_dynamic_slots().compile()
        # Assert
        assert compiled["agent_config"]["allow_dynamic_slots"] is True

    def test_opt_in_preserves_existing_agent_config_knobs(self) -> None:
        # Arrange / Act
        compiled = (
            _make_spec()
            .with_agent_config(max_iterations=17, temperature=0.42)
            .with_dynamic_slots()
            .compile()
        )
        # Assert
        assert compiled["agent_config"]["max_iterations"] == 17


# ── 2. Boundary — default-off back-compat + explicit disable ─────────


class TestWithDynamicSlotsBackCompat:
    def test_not_opting_in_omits_key_from_agent_config(self) -> None:
        # Arrange / Act
        compiled = _make_spec().with_agent_config(max_iterations=20).compile()
        # Assert
        assert "allow_dynamic_slots" not in compiled["agent_config"]

    def test_not_opting_in_serializes_without_the_key_anywhere(self) -> None:
        """Byte-identical guarantee: the new key never appears when off."""
        # Arrange / Act
        compiled = _make_spec().with_agent_config(max_iterations=20).compile()
        serialized = json.dumps(compiled)
        # Assert
        assert "allow_dynamic_slots" not in serialized

    def test_no_agent_config_block_when_off_and_untouched(self) -> None:
        """A workflow that never touches agent_config stays unchanged."""
        # Arrange / Act
        compiled = _make_spec().compile()
        # Assert
        assert "agent_config" not in compiled

    def test_explicit_disable_turns_a_prior_opt_in_back_off(self) -> None:
        # Arrange / Act
        compiled = _make_spec().with_dynamic_slots().with_dynamic_slots(False).compile()
        # Assert — off means the key is omitted (no explicit false)
        assert "agent_config" not in compiled or (
            "allow_dynamic_slots" not in compiled["agent_config"]
        )


# ── 3. Object-state — immutability + order-independent composition ───


class TestWithDynamicSlotsImmutability:
    def test_opt_in_returns_new_object_leaving_original_unchanged(self) -> None:
        # Arrange
        base = _make_spec().with_agent_config(max_iterations=20)
        # Act
        opted_in = base.with_dynamic_slots()
        # Assert — original builder untouched, new one carries the flag
        assert base._agent_config is not None
        assert base._agent_config.allow_dynamic_slots is None
        assert opted_in._agent_config.allow_dynamic_slots is True

    def test_flag_survives_agent_config_after_opt_in(self) -> None:
        """with_agent_config AFTER with_dynamic_slots must not wipe the flag."""
        # Arrange / Act — reverse order of the "preserves knobs" test
        compiled = _make_spec().with_dynamic_slots().with_agent_config(max_iterations=11).compile()
        # Assert
        assert compiled["agent_config"]["allow_dynamic_slots"] is True
        assert compiled["agent_config"]["max_iterations"] == 11


# ── 4. Object-state — round-trip parity ──────────────────────────────


class TestWithDynamicSlotsRoundTrip:
    def test_compile_then_from_dict_preserves_opt_in(self) -> None:
        # Arrange
        compiled = _make_spec().with_dynamic_slots().compile()
        # Act
        loaded = WorkflowSpec._from_dict(compiled)
        recompiled = loaded.compile()
        # Assert
        assert recompiled["agent_config"]["allow_dynamic_slots"] is True
