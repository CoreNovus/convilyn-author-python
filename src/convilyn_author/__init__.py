"""Convilyn author SDK — build tool servers for the Convilyn platform.

Define a tool server::

    from convilyn_author import ToolServer, ToolContext

    server = ToolServer("my-analyzer")

    @server.tool()
    def analyze(text: str, ctx: ToolContext) -> dict:
        return {"length": len(text)}

    server.run()                       # local dev; `convilyn-author push` to ship

Workflow authoring lives in the Convilyn chat Builder. This SDK is the
tool-server SDK: build, register, verify and operate MCP tool servers the
platform's workflows call.

The public surface — everything reachable as ``from convilyn_author import X`` plus
the ``convilyn-author`` CLI — follows Semantic Versioning. See
``docs/STABILITY.md`` for the stability contract and the deprecation register;
``convilyn_author._internal`` is implementation detail and exempt.
"""

from convilyn_author._internal.confirmation import (
    CONFIRMATION_TTL_SECONDS,
    ConfirmationInvalidError,
    mint_confirmation_token,
    verify_confirmation_token,
)
from convilyn_author._version import __version__
from convilyn_author.catalog import ToolCatalog
from convilyn_author.client import ConvilynClient
from convilyn_author.context import ToolContext
from convilyn_author.data_store import InMemoryDataStore
from convilyn_author.manifest import ConvilynManifest
from convilyn_author.server import ConvilynServer, ToolServer
from convilyn_author.types import (
    ComplianceReport,
    ComplianceResult,
    ToolDataRef,
    ToolError,
    ToolResult,
    ToolSpec,
)

__all__ = [
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
]
