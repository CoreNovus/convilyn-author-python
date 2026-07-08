"""Tool catalog — browse existing platform tools.

Provides a read-only directory of tools available on the Convilyn platform.
Phase 1 uses a static JSON catalog; Phase 2 will fetch from a live API.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("convilyn_sdk.catalog")


class ToolInfo(BaseModel):
    """Metadata for a single tool."""

    name: str
    server: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    capabilities: list[str] = Field(default_factory=list)


class ServerInfo(BaseModel):
    """Metadata for an MCP server."""

    name: str
    description: str
    tool_count: int = 0
    capabilities: list[str] = Field(default_factory=list)


class ToolCatalog:
    """Platform tool catalog — browse existing available tools.

    Usage::

        catalog = ToolCatalog()
        catalog.list_servers()
        # → [ServerInfo(name="resume-profile-mcp", ...), ...]

        catalog.list_tools(server="resume-profile-mcp")
        # → [ToolInfo(name="parse_document", ...), ...]

        catalog.describe("resume-profile-mcp:parse_document")
        # → ToolInfo(name="parse_document", ...)

        catalog.search("translate")
        # → [ToolInfo(name="translate_text", ...)]
    """

    def __init__(self, catalog_path: str | Path | None = None) -> None:
        self._servers: list[ServerInfo] = []
        self._tools: list[ToolInfo] = []

        if catalog_path is not None:
            self._load(Path(catalog_path))

    def _load(self, path: Path) -> None:
        """Load catalog from a JSON file."""
        if not path.exists():
            logger.warning("Catalog file not found: %s", path)
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        for srv in data.get("servers", []):
            tools = srv.get("tools", [])
            self._servers.append(ServerInfo(
                name=srv["name"],
                description=srv.get("description", ""),
                tool_count=len(tools),
                capabilities=srv.get("capabilities", []),
            ))
            for tool in tools:
                self._tools.append(ToolInfo(
                    name=tool["name"],
                    server=srv["name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("input_schema", {}),
                    output_schema=tool.get("output_schema"),
                    capabilities=tool.get("capabilities", []),
                ))

    def list_servers(self) -> list[ServerInfo]:
        """List all MCP servers."""
        return list(self._servers)

    def list_tools(self, server: str | None = None) -> list[ToolInfo]:
        """List tools, optionally filtered by server name."""
        if server is None:
            return list(self._tools)
        return [t for t in self._tools if t.server == server]

    def describe(self, tool_spec: str) -> ToolInfo | None:
        """Get tool details by ``server:tool`` format.

        Args:
            tool_spec: Tool identifier, e.g. "resume-profile-mcp:parse_document".

        Returns:
            ToolInfo if found, None otherwise.
        """
        if ":" not in tool_spec:
            # Search by tool name only
            for t in self._tools:
                if t.name == tool_spec:
                    return t
            return None

        server_name, tool_name = tool_spec.split(":", 1)
        for t in self._tools:
            if t.server == server_name and t.name == tool_name:
                return t
        return None

    def search(self, query: str) -> list[ToolInfo]:
        """Search tools by name, description, or capabilities."""
        query_lower = query.lower()
        results: list[ToolInfo] = []
        for t in self._tools:
            if (
                query_lower in t.name.lower()
                or query_lower in t.description.lower()
                or any(query_lower in c.lower() for c in t.capabilities)
            ):
                results.append(t)
        return results
