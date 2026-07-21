"""Builder-level tests for ``WorkflowSpec.with_multi_role``.

Exercises both signature shapes (bare-string roles and structured
:class:`AgentRole` Protocol instances), the auto-derivation of the
specialists allowlist, immutability of the builder, and the wire
shape produced by ``compile()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from convilyn_author import (
    AgentRole,
    RoleConfig,
    WorkflowSpec,
)
from convilyn_author.workflow_validator import validate_workflow_spec

# ── Helpers: concrete AgentRole Protocol implementations ──────────


@dataclass(frozen=True)
class _AgentRoleFixture:
    """Frozen dataclass conforming to the :class:`AgentRole` Protocol.

    Frozen + minimal so the test exercises the *Protocol* contract, not
    any base-class behaviour. Authors in the wild would write something
    similar.
    """

    role: str
    tool_allowlist: list[str] | None = field(default=None)


def _make_spec() -> WorkflowSpec:
    return (
        WorkflowSpec("multi_agent_test", name="Multi-Agent Test")
        .with_input(types=["document"])
        .with_output(format="json")
        .add_phase("analyze", "Initial analysis phase.")
    )


# ── 1. Logic — happy path ────────────────────────────────────────────


class TestWithMultiRoleLogic:
    def test_bare_string_roles_compile_to_wire_shape(self) -> None:
        spec = _make_spec().with_multi_role(active_specialists=["data_engineer", "qa_analyst"])
        compiled = spec.compile()
        assert "multi_agent" in compiled
        block = compiled["multi_agent"]
        assert block["active_specialists"] == ["data_engineer", "qa_analyst"]
        # `specialists` omitted when no allowlists supplied.
        assert "specialists" not in block

    def test_agent_role_protocol_auto_populates_allowlist(self) -> None:
        de = _AgentRoleFixture(
            role="data_engineer",
            tool_allowlist=["doc-parser:extract_text"],
        )
        qa = _AgentRoleFixture(role="qa_analyst")  # no allowlist
        spec = _make_spec().with_multi_role(active_specialists=[de, qa])
        block = spec.compile()["multi_agent"]
        assert block["active_specialists"] == ["data_engineer", "qa_analyst"]
        assert block["specialists"] == {
            "data_engineer": {"tools": ["doc-parser:extract_text"]},
        }

    def test_explicit_specialists_map_wins_over_protocol_derivation(self) -> None:
        de = _AgentRoleFixture(
            role="data_engineer",
            tool_allowlist=["derived:tool"],
        )
        spec = _make_spec().with_multi_role(
            active_specialists=[de],
            specialists={
                "data_engineer": RoleConfig(tools=["explicit:tool"]),
            },
        )
        block = spec.compile()["multi_agent"]
        # Explicit map overrides the Protocol-derived entry.
        assert block["specialists"]["data_engineer"]["tools"] == ["explicit:tool"]

    def test_protocol_satisfies_runtime_check(self) -> None:
        """Belt-and-braces: a frozen dataclass with the right shape IS an AgentRole."""
        de = _AgentRoleFixture(role="data_engineer", tool_allowlist=["a:b"])
        assert isinstance(de, AgentRole)

    def test_compile_emits_full_block_with_all_fields(self) -> None:
        spec = _make_spec().with_multi_role(
            active_specialists=["data_engineer"],
            workflow_context={"locale_hints": ["en"]},
            rule_bundle_ref="finance/v1",
            rule_bundle_version="1.0.0",
            autonomy_level="autonomous",
            max_total_tool_calls=42,
            max_role_visits=5,
        )
        block = spec.compile()["multi_agent"]
        assert block["workflow_context"] == {"locale_hints": ["en"]}
        assert block["rule_bundle_ref"] == "finance/v1"
        assert block["rule_bundle_version"] == "1.0.0"
        assert block["autonomy_level"] == "autonomous"
        assert block["max_total_tool_calls"] == 42
        assert block["max_role_visits"] == 5


# ── 2. Boundary — immutability, replace-on-recall, mixed inputs ─────


class TestWithMultiRoleBoundary:
    def test_immutability_preserves_original(self) -> None:
        base = _make_spec()
        with_ma = base.with_multi_role(active_specialists=["a"])
        assert base._multi_agent is None
        assert with_ma._multi_agent is not None

    def test_calling_twice_replaces_block(self) -> None:
        spec = (
            _make_spec()
            .with_multi_role(active_specialists=["a"])
            .with_multi_role(active_specialists=["b"])
        )
        block = spec.compile()["multi_agent"]
        assert block["active_specialists"] == ["b"]

    def test_mixed_str_and_agent_role_supported(self) -> None:
        de = _AgentRoleFixture(role="data_engineer", tool_allowlist=["a:b"])
        spec = _make_spec().with_multi_role(active_specialists=[de, "qa_analyst"])
        block = spec.compile()["multi_agent"]
        assert block["active_specialists"] == ["data_engineer", "qa_analyst"]
        assert "qa_analyst" not in block["specialists"]


# ── 3. Error — duplicate roles, empty strings rejected ──────────────


class TestWithMultiRoleErrors:
    def test_duplicate_string_roles_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate role"):
            _make_spec().with_multi_role(active_specialists=["data_engineer", "data_engineer"])

    def test_empty_role_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="role cannot be empty"):
            _make_spec().with_multi_role(active_specialists=[""])

    def test_validator_catches_stray_specialists_keys(self) -> None:
        """The SDK validator mirrors the backend's stray-key check."""
        compiled = _make_spec().compile()
        # Hand-craft a misconfigured block (bypass builder) and inject.
        compiled["multi_agent"] = {
            "active_specialists": ["data_engineer"],
            "specialists": {"qa_analyst": {"tools": ["a:b"]}},
        }
        result = validate_workflow_spec(compiled)
        assert not result.valid
        assert any("roles not in active_specialists" in err for err in result.errors)


# ── 4. Object-state — round-trip via _from_dict / save+load ─────────


class TestWithMultiRoleRoundTrip:
    def test_compile_then_from_dict_preserves_block(self) -> None:
        spec = _make_spec().with_multi_role(
            active_specialists=["data_engineer"],
            workflow_context={"locale_hints": ["zh-TW"]},
        )
        compiled = spec.compile()
        loaded = WorkflowSpec._from_dict(compiled)
        assert loaded.compile()["multi_agent"] == compiled["multi_agent"]
