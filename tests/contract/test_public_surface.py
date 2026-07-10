"""Public-API contract — the published author-SDK surface must not drift silently.

Keystone guard for the SDK's stability promise (see ``docs/STABILITY.md``). It
freezes the public surface so any change to it is a *deliberate, reviewed* act:

* ``convilyn_sdk.__all__`` — the exact set of top-level exports.
* The core abstractions (``ToolServer`` / ``WorkflowSpec`` / …) and their
  contract methods.
* The ``convilyn-author`` CLI command tree.
* The 2.0.0 removal invariants (issue #1740): the dropped aliases + the 13
  granular ``*Config`` models stay off the top level, and the latter remain
  reachable from ``convilyn_sdk.workflow_policies``.

…and it asserts that nothing truly-internal from ``convilyn_sdk._internal``
leaks into the public ``convilyn_sdk`` namespace.

To change the public API on purpose, update the frozen sets below **and** add a
``CHANGELOG.md`` entry in the same commit.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import convilyn_sdk
from convilyn_sdk.cli.main import cli

_SDK_ROOT = Path(__file__).resolve().parents[2]

# ── Frozen public export set ─────────────────────────────────────────
# Changing this set IS the act of changing the public API. Pair any edit
# with a CHANGELOG.md entry + a SemVer bump (see docs/STABILITY.md).
FROZEN_ALL = {
    "AgentRole",
    "CheckpointConfig",
    "ComplianceReport",
    "ComplianceResult",
    "CONFIRMATION_TTL_SECONDS",
    "ConfirmationInvalidError",
    "ConvilynClient",
    "ConvilynManifest",
    "ConvilynServer",
    "FailureRule",
    "FallbackPolicy",
    "HumanReviewPolicy",
    "InMemoryDataStore",
    "mint_confirmation_token",
    "MultiRoleConfig",
    "OutputValidationPolicy",
    "PatternCheck",
    "RequiredSection",
    "RetryPolicy",
    "RoleConfig",
    "StructureCheck",
    "TerminalFailureRule",
    "TimeoutPolicy",
    "ToolCatalog",
    "ToolContext",
    "ToolDataRef",
    "ToolError",
    "ToolResult",
    "ToolServer",
    "ToolSpec",
    "ToolStage",
    "verify_confirmation_token",
    "WorkflowSpec",
    "__version__",
}

# Surface removed in the 2.0.0 major (issue #1740). These names MUST NOT be
# reachable as top-level ``convilyn_sdk.X`` anymore. The 13 granular ``*Config``
# models keep living one layer down in ``convilyn_sdk.workflow_policies`` (the
# advanced, non-SemVer surface) — asserted separately below.
REMOVED_TOP_LEVEL_2_0 = {
    # 13 granular policy models (previously re-exported via workflow_policies)
    "FailureRuleConfig",
    "FallbackPolicyConfig",
    "GoalCriteriaConfig",
    "QaPolicyConfig",
    "QualityCheckConfig",
    "RetryPolicyConfig",
    "RoutingPolicyConfig",
    "SectionConfig",
    "SlotPolicyConfig",
    "StructuralCheckConfig",
    "TaskPolicyConfig",
    "TerminalFailurePolicyConfig",
    "ToolStageConfig",
    # deprecated aliases
    "Specialist",
    "SpecialistConfigModel",
    "MultiAgentConfig",
}

# The 13 granular models stay importable from this submodule after the top-level
# re-export was dropped — power-user access to the typed wire shapes.
RELOCATED_TO_WORKFLOW_POLICIES = {
    "FailureRuleConfig",
    "FallbackPolicyConfig",
    "GoalCriteriaConfig",
    "QaPolicyConfig",
    "QualityCheckConfig",
    "RetryPolicyConfig",
    "RoutingPolicyConfig",
    "SectionConfig",
    "SlotPolicyConfig",
    "StructuralCheckConfig",
    "TaskPolicyConfig",
    "TerminalFailurePolicyConfig",
    "ToolStageConfig",
}

# Truly-internal symbols (transport / HMAC / JSON-RPC / server runtime /
# template marketplace). These must NEVER be reachable as ``convilyn_sdk.X``.
INTERNAL_DENYLIST = (
    "verify_signature",
    "InvalidSignatureError",
    "MCPError",
    "MCPToolResult",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ToolContextPayload",
    "PolicyProtocol",
    "merge_wire_blocks",
    "apply_policies",
    "parse_jsonrpc_request",
    "start_server",
    "ConvilynStartupError",
    "TemplateEntry",
    "install_template",
    "load_catalog",
)

# Core abstractions → the contract methods callers depend on (presence check,
# so adding a method stays backward-compatible while removal/rename fails).
REQUIRED_METHODS = {
    "ToolServer": {"tool", "synth", "run", "call_tool", "tool_names", "get_tool"},
    "WorkflowSpec": {"compile", "save", "load"},
    "ConvilynManifest": {"to_dict", "to_json", "save", "load"},
    "ToolCatalog": {"list_servers", "list_tools", "describe", "search"},
}

# convilyn-author CLI command tree (frozen).
CLI_TOP = {
    "init",
    "synth",
    "dev",
    "test",
    "workflow",
    "push",
    "deploy",
    "rollback",
    "logs",
    "template",
    "status",
    "doctor",
}
CLI_WORKFLOW = {"init", "build"}
CLI_TEMPLATE = {"list", "install", "fork"}

TESTING_HELPERS = (
    "ConvilynTestRunner",
    "WorkflowTestRunner",
    "WorkflowTestResult",
    "assert_tool_success",
    "assert_tool_error",
    "assert_schema_valid",
)


# ── __all__ is frozen ────────────────────────────────────────────────


def test_all_matches_frozen_set() -> None:
    """``convilyn_sdk.__all__`` must equal the frozen contract set exactly."""
    actual = set(convilyn_sdk.__all__)
    assert actual == FROZEN_ALL, (
        "public __all__ drifted — added "
        f"{sorted(actual - FROZEN_ALL)}, removed {sorted(FROZEN_ALL - actual)}. "
        "If intentional, update FROZEN_ALL here AND add a CHANGELOG entry."
    )


def test_every_export_is_importable() -> None:
    """Every name in ``__all__`` must resolve (no dangling export)."""
    missing = [name for name in convilyn_sdk.__all__ if not hasattr(convilyn_sdk, name)]
    assert not missing, f"declared in __all__ but missing: {missing}"


def test_no_implicit_public_exports() -> None:
    """No non-underscore, non-module attribute may exist outside ``__all__``."""
    public_attrs = {
        name
        for name, value in vars(convilyn_sdk).items()
        if not name.startswith("_") and not inspect.ismodule(value)
    }
    extra = public_attrs - set(convilyn_sdk.__all__)
    assert not extra, f"implicit public exports not in __all__: {sorted(extra)}"


# ── _internal stays internal ─────────────────────────────────────────


def test_internal_symbols_not_reachable_from_top_level() -> None:
    """Transport / HMAC / JSON-RPC / runtime internals must not be ``convilyn_sdk.X``."""
    leaked = [name for name in INTERNAL_DENYLIST if hasattr(convilyn_sdk, name)]
    assert not leaked, f"internal implementation symbols leaked publicly: {leaked}"


# ── Core abstractions ────────────────────────────────────────────────


def test_core_abstractions_expose_contract_methods() -> None:
    """ToolServer / WorkflowSpec / ConvilynManifest / ToolCatalog keep their methods."""
    for cls_name, required in REQUIRED_METHODS.items():
        cls = getattr(convilyn_sdk, cls_name)
        public = {name for name in dir(cls) if not name.startswith("_")}
        missing = required - public
        assert not missing, f"{cls_name} lost contract methods: {sorted(missing)}"


def test_tool_server_data_store_is_a_property() -> None:
    """``ToolServer.data_store`` is a read accessor, not a settable attribute."""
    accessor = inspect.getattr_static(convilyn_sdk.ToolServer, "data_store")
    assert isinstance(accessor, property)


def test_testing_helpers_are_importable() -> None:
    """The public author-testing helpers stay reachable under ``convilyn_sdk.testing``."""
    import convilyn_sdk.testing as testing

    missing = [name for name in TESTING_HELPERS if not hasattr(testing, name)]
    assert not missing, f"testing helpers missing: {missing}"


# ── CLI command tree ─────────────────────────────────────────────────


def test_cli_command_tree_frozen() -> None:
    """The ``convilyn-author`` command tree (top + subgroups) is frozen."""
    assert set(cli.commands) == CLI_TOP, sorted(cli.commands)
    assert set(cli.commands["workflow"].commands) == CLI_WORKFLOW
    assert set(cli.commands["template"].commands) == CLI_TEMPLATE


# ── 2.0.0 removal invariants (issue #1740) ───────────────────────────


def test_removed_2_0_surface_is_gone_from_top_level() -> None:
    """The deprecated surface dropped in 2.0.0 must not be reachable as ``convilyn_sdk.X``.

    Covers the 13 granular ``*Config`` models plus the ``Specialist`` /
    ``SpecialistConfigModel`` / ``MultiAgentConfig`` aliases. Pairs with the
    ``CHANGELOG.md`` "Removed" section for 2.0.0.
    """
    still_present = sorted(n for n in REMOVED_TOP_LEVEL_2_0 if hasattr(convilyn_sdk, n))
    assert not still_present, (
        f"surface removed in 2.0.0 is still reachable as convilyn_sdk.X: {still_present}"
    )
    leaked_into_all = REMOVED_TOP_LEVEL_2_0 & set(convilyn_sdk.__all__)
    assert not leaked_into_all, f"removed names still in __all__: {sorted(leaked_into_all)}"


def test_specialist_module_path_is_removed() -> None:
    """``import convilyn_sdk.specialist`` must fail after the 2.0.0 removal."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("convilyn_sdk.specialist")


def test_granular_models_remain_in_workflow_policies_submodule() -> None:
    """The granular ``*Config`` models keep living under ``convilyn_sdk.workflow_policies``.

    The top-level re-export was dropped (above), but the typed wire models stay
    importable one layer down for power users and for the granular builder
    methods (``with_task_policy`` / ``with_routing`` / ``with_qa_policy``).
    """
    import convilyn_sdk.workflow_policies as wp

    missing = [n for n in RELOCATED_TO_WORKFLOW_POLICIES if not hasattr(wp, n)]
    assert not missing, f"granular models vanished from workflow_policies: {missing}"


# ── Stability doc anchor ─────────────────────────────────────────────


def test_stability_doc_exists_and_names_the_contract() -> None:
    """``docs/STABILITY.md`` must exist and name the public-surface anchor."""
    doc = _SDK_ROOT / "docs" / "STABILITY.md"
    assert doc.exists(), f"missing stability policy doc at {doc}"
    text = doc.read_text(encoding="utf-8")
    assert "convilyn_sdk.__all__" in text
    assert "convilyn_sdk._internal" in text
