"""Convilyn author SDK — build tool servers and workflows for the Convilyn platform.

Define a tool server::

    from convilyn_sdk import ToolServer, ToolContext

    server = ToolServer("my-analyzer")

    @server.tool()
    def analyze(text: str, ctx: ToolContext) -> dict:
        return {"length": len(text)}

    server.run()                       # local dev; `convilyn-author push` to ship

Author a workflow spec::

    from convilyn_sdk import WorkflowSpec

    spec = WorkflowSpec("doc-review").with_goal("Summarise the document")
    compiled = spec.compile()

The public surface — everything reachable as ``from convilyn_sdk import X`` plus
the ``convilyn-author`` CLI — follows Semantic Versioning. See
``docs/STABILITY.md`` for the stability contract and the deprecation register;
``convilyn_sdk._internal`` is implementation detail and exempt.
"""

from convilyn_sdk._internal.confirmation import (
    CONFIRMATION_TTL_SECONDS,
    ConfirmationInvalidError,
    mint_confirmation_token,
    verify_confirmation_token,
)
from convilyn_sdk._version import __version__
from convilyn_sdk.agent_role import AgentRole
from convilyn_sdk.catalog import ToolCatalog
from convilyn_sdk.client import ConvilynClient
from convilyn_sdk.context import ToolContext
from convilyn_sdk.data_store import InMemoryDataStore
from convilyn_sdk.manifest import ConvilynManifest
from convilyn_sdk.policies import (
    FailureRule,
    FallbackPolicy,
    HumanReviewPolicy,
    OutputValidationPolicy,
    PatternCheck,
    RequiredSection,
    RetryPolicy,
    StructureCheck,
    TerminalFailureRule,
    TimeoutPolicy,
    ToolStage,
)
from convilyn_sdk.server import ConvilynServer, ToolServer
from convilyn_sdk.types import (
    ComplianceReport,
    ComplianceResult,
    ToolDataRef,
    ToolError,
    ToolResult,
    ToolSpec,
)
from convilyn_sdk.workflow import WorkflowSpec
from convilyn_sdk.workflow_advanced_types import (
    CheckpointConfig,
    MultiRoleConfig,
    RoleConfig,
)

__all__ = [
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
]
