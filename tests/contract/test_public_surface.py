"""Public-API contract — the published author-SDK surface must not drift silently.

Keystone guard for the SDK's stability promise (see ``docs/STABILITY.md``). It
freezes the public surface so any change to it is a *deliberate, reviewed* act:

* ``convilyn_author.__all__`` — the exact set of top-level exports.
* The core abstractions (``ToolServer`` / ``ConvilynManifest`` / …) and their
  contract methods.
* The ``convilyn-author`` CLI command tree.
* The 2.0.0 removal invariants (issue #1740): the dropped aliases + the 13
  granular ``*Config`` models stay off the top level.

…and it asserts that nothing truly-internal from ``convilyn_author._internal``
leaks into the public ``convilyn_author`` namespace.

To change the public API on purpose, update the frozen sets below **and** add a
``CHANGELOG.md`` entry in the same commit.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import convilyn_author
from convilyn_author.cli.main import cli

_SDK_ROOT = Path(__file__).resolve().parents[2]

# ── Frozen public export set ─────────────────────────────────────────
# Changing this set IS the act of changing the public API. Pair any edit
# with a CHANGELOG.md entry + a SemVer bump (see docs/STABILITY.md).
# This is the tool-server-only surface (release 2.3.0b1): workflow
# authoring was removed and lives in the Convilyn chat Builder.
FROZEN_ALL = {
    "ComplianceReport",
    "ComplianceResult",
    "CONFIRMATION_TTL_SECONDS",
    "ConfirmationInvalidError",
    "ConvilynClient",
    "ConvilynManifest",
    "ConvilynServer",
    "InMemoryDataStore",
    "mint_confirmation_token",
    "ToolCatalog",
    "ToolContext",
    "ToolDataRef",
    "ToolError",
    "ToolResult",
    "ToolServer",
    "ToolSpec",
    "verify_confirmation_token",
    "__version__",
}

# Surface removed in the 2.0.0 major (issue #1740). These names MUST NOT be
# reachable as top-level ``convilyn_author.X`` anymore. The 13 granular
# ``*Config`` models and the deprecated aliases were dropped from the top level;
# the workflow-authoring surface that once hosted them is fully removed.
REMOVED_TOP_LEVEL_2_0 = {
    # 13 granular policy models (previously re-exported)
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

# Truly-internal symbols (transport / HMAC / JSON-RPC / server runtime /
# template marketplace). These must NEVER be reachable as ``convilyn_author.X``.
INTERNAL_DENYLIST = (
    "verify_signature",
    "InvalidSignatureError",
    "MCPError",
    "MCPToolResult",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "ToolContextPayload",
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
    "ConvilynManifest": {"to_dict", "to_json", "save", "load"},
    "ToolCatalog": {"list_servers", "list_tools", "describe", "search"},
}

# convilyn-author CLI command tree (frozen).
CLI_TOP = {
    "init",
    "synth",
    "dev",
    "test",
    "push",
    "deploy",
    "rollback",
    "logs",
    "template",
    "status",
    "doctor",
}
CLI_TEMPLATE = {"list", "install", "fork"}

TESTING_HELPERS = (
    "ConvilynTestRunner",
    "assert_tool_success",
    "assert_tool_error",
    "assert_schema_valid",
)


# ── __all__ is frozen ────────────────────────────────────────────────


def test_all_matches_frozen_set() -> None:
    """``convilyn_author.__all__`` must equal the frozen contract set exactly."""
    actual = set(convilyn_author.__all__)
    assert actual == FROZEN_ALL, (
        "public __all__ drifted — added "
        f"{sorted(actual - FROZEN_ALL)}, removed {sorted(FROZEN_ALL - actual)}. "
        "If intentional, update FROZEN_ALL here AND add a CHANGELOG entry."
    )


def test_every_export_is_importable() -> None:
    """Every name in ``__all__`` must resolve (no dangling export)."""
    missing = [name for name in convilyn_author.__all__ if not hasattr(convilyn_author, name)]
    assert not missing, f"declared in __all__ but missing: {missing}"


def test_no_implicit_public_exports() -> None:
    """No non-underscore, non-module attribute may exist outside ``__all__``."""
    public_attrs = {
        name
        for name, value in vars(convilyn_author).items()
        if not name.startswith("_") and not inspect.ismodule(value)
    }
    extra = public_attrs - set(convilyn_author.__all__)
    assert not extra, f"implicit public exports not in __all__: {sorted(extra)}"


# ── _internal stays internal ─────────────────────────────────────────


def test_internal_symbols_not_reachable_from_top_level() -> None:
    """Transport / HMAC / JSON-RPC / runtime internals must not be ``convilyn_author.X``."""
    leaked = [name for name in INTERNAL_DENYLIST if hasattr(convilyn_author, name)]
    assert not leaked, f"internal implementation symbols leaked publicly: {leaked}"


# ── Core abstractions ────────────────────────────────────────────────


def test_core_abstractions_expose_contract_methods() -> None:
    """ToolServer / ConvilynManifest / ToolCatalog keep their contract methods."""
    for cls_name, required in REQUIRED_METHODS.items():
        cls = getattr(convilyn_author, cls_name)
        public = {name for name in dir(cls) if not name.startswith("_")}
        missing = required - public
        assert not missing, f"{cls_name} lost contract methods: {sorted(missing)}"


def test_tool_server_data_store_is_a_property() -> None:
    """``ToolServer.data_store`` is a read accessor, not a settable attribute."""
    accessor = inspect.getattr_static(convilyn_author.ToolServer, "data_store")
    assert isinstance(accessor, property)


def test_testing_helpers_are_importable() -> None:
    """The public author-testing helpers stay reachable under ``convilyn_author.testing``."""
    import convilyn_author.testing as testing

    missing = [name for name in TESTING_HELPERS if not hasattr(testing, name)]
    assert not missing, f"testing helpers missing: {missing}"


# ── CLI command tree ─────────────────────────────────────────────────


def test_cli_command_tree_frozen() -> None:
    """The ``convilyn-author`` command tree (top + subgroups) is frozen."""
    assert set(cli.commands) == CLI_TOP, sorted(cli.commands)
    assert set(cli.commands["template"].commands) == CLI_TEMPLATE


# ── 2.0.0 removal invariants (issue #1740) ───────────────────────────


def test_removed_2_0_surface_is_gone_from_top_level() -> None:
    """The deprecated surface dropped in 2.0.0 must not be reachable as ``convilyn_author.X``.

    Covers the 13 granular ``*Config`` models plus the ``Specialist`` /
    ``SpecialistConfigModel`` / ``MultiAgentConfig`` aliases. Pairs with the
    ``CHANGELOG.md`` "Removed" section for 2.0.0.
    """
    still_present = sorted(n for n in REMOVED_TOP_LEVEL_2_0 if hasattr(convilyn_author, n))
    assert not still_present, (
        f"surface removed in 2.0.0 is still reachable as convilyn_author.X: {still_present}"
    )
    leaked_into_all = REMOVED_TOP_LEVEL_2_0 & set(convilyn_author.__all__)
    assert not leaked_into_all, f"removed names still in __all__: {sorted(leaked_into_all)}"


def test_specialist_module_path_is_removed() -> None:
    """``import convilyn_author.specialist`` must fail after the 2.0.0 removal."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("convilyn_author.specialist")


# ── Stability doc anchor ─────────────────────────────────────────────


def test_stability_doc_exists_and_names_the_contract() -> None:
    """``docs/STABILITY.md`` must exist and name the public-surface anchor."""
    doc = _SDK_ROOT / "docs" / "STABILITY.md"
    assert doc.exists(), f"missing stability policy doc at {doc}"
    text = doc.read_text(encoding="utf-8")
    assert "convilyn_author.__all__" in text
    assert "convilyn_author._internal" in text
