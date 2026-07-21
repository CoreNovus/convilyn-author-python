"""Builder-level tests for ``WorkflowSpec.with_resume_boundary``.

Exercises additive composition, slot normalisation (raw dict ↔
SlotConfig), the validator's phase-reference warning, and round-trip
parity via ``_from_dict``.
"""

from __future__ import annotations

from convilyn_author import WorkflowSpec
from convilyn_author.workflow_types import SlotConfig
from convilyn_author.workflow_validator import validate_workflow_spec


def _make_spec() -> WorkflowSpec:
    return (
        WorkflowSpec("checkpoint_test", name="Checkpoint Test")
        .with_input(types=["document"])
        .with_output(format="json")
        .add_phase("analyze", "First phase.")
        .add_phase("synthesize", "Second phase.")
    )


# ── 1. Logic — happy path ────────────────────────────────────────────


class TestWithResumeBoundaryLogic:
    def test_single_checkpoint_compiles_to_wire_shape(self) -> None:
        spec = _make_spec().with_resume_boundary(
            "disambiguate_topic",
            after_phase="analyze",
            reason="multiple plausible topics",
            slots=[SlotConfig(slot_id="topic", type="text", question="Which topic?")],
        )
        compiled = spec.compile()
        assert "checkpoints" in compiled
        cp = compiled["checkpoints"]["disambiguate_topic"]
        assert cp["after_phase"] == "analyze"
        assert cp["reason"] == "multiple plausible topics"
        assert cp["slots"][0]["slot_id"] == "topic"

    def test_multiple_checkpoints_accumulate(self) -> None:
        spec = (
            _make_spec()
            .with_resume_boundary(
                "cp1",
                after_phase="analyze",
                reason="r1",
                slots=[SlotConfig(slot_id="s1", type="text", question="?")],
            )
            .with_resume_boundary(
                "cp2",
                after_phase="synthesize",
                reason="r2",
                slots=[SlotConfig(slot_id="s2", type="text", question="?")],
            )
        )
        compiled = spec.compile()
        assert set(compiled["checkpoints"].keys()) == {"cp1", "cp2"}

    def test_slot_mapping_normalised_to_slotconfig(self) -> None:
        """Raw dict slots are validated via SlotConfig.model_validate."""
        spec = _make_spec().with_resume_boundary(
            "cp_raw",
            after_phase="analyze",
            reason="r",
            slots=[
                {
                    "slot_id": "topic",
                    "type": "text",
                    "question": "Which?",
                }
            ],
        )
        cp = spec.compile()["checkpoints"]["cp_raw"]
        assert cp["slots"][0]["slot_id"] == "topic"


# ── 2. Boundary — replacement semantics, immutability ──────────────


class TestWithResumeBoundaryBoundary:
    def test_same_id_replaces_prior_entry(self) -> None:
        slot1 = SlotConfig(slot_id="s1", type="text", question="?")
        slot2 = SlotConfig(slot_id="s2", type="text", question="?")
        spec = (
            _make_spec()
            .with_resume_boundary("cp", after_phase="analyze", reason="first", slots=[slot1])
            .with_resume_boundary("cp", after_phase="synthesize", reason="second", slots=[slot2])
        )
        cp = spec.compile()["checkpoints"]["cp"]
        # Last write wins — matches dict semantics.
        assert cp["reason"] == "second"
        assert cp["slots"][0]["slot_id"] == "s2"

    def test_immutability_preserves_original(self) -> None:
        slot = SlotConfig(slot_id="s", type="text", question="?")
        base = _make_spec()
        with_cp = base.with_resume_boundary("cp", after_phase="analyze", reason="r", slots=[slot])
        assert base._checkpoints == {}
        assert "cp" in with_cp._checkpoints


# ── 3. Error — validator catches missing fields + unknown phase ─────


class TestWithResumeBoundaryErrors:
    def test_validator_warns_on_unknown_phase_ref(self) -> None:
        slot = SlotConfig(slot_id="s", type="text", question="?")
        spec = _make_spec().with_resume_boundary(
            "cp", after_phase="does_not_exist", reason="r", slots=[slot]
        )
        result = validate_workflow_spec(spec.compile())
        assert result.valid is True  # warning, not error
        assert any("unknown phase 'does_not_exist'" in w for w in result.warnings)

    def test_validator_errors_on_missing_slots(self) -> None:
        """Bypass-the-builder: directly construct a malformed spec dict."""
        compiled = _make_spec().compile()
        compiled["checkpoints"] = {
            "bad_cp": {"after_phase": "analyze", "reason": "r", "slots": []},
        }
        result = validate_workflow_spec(compiled)
        assert not result.valid
        assert any("must declare at least one slot" in e for e in result.errors)


# ── 4. Object-state — round-trip parity ─────────────────────────────


class TestWithResumeBoundaryRoundTrip:
    def test_compile_then_from_dict_preserves_checkpoints(self) -> None:
        slot = SlotConfig(
            slot_id="s",
            type="multi_choice",
            question="?",
            options=["a", "b"],
        )
        spec = _make_spec().with_resume_boundary(
            "cp_rt", after_phase="analyze", reason="r", slots=[slot]
        )
        compiled = spec.compile()
        loaded = WorkflowSpec._from_dict(compiled)
        assert loaded.compile()["checkpoints"] == compiled["checkpoints"]
