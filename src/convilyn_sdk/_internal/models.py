"""Vendored data models for Convilyn protocol communication.

These are a subset of the internal mcp-shared models, vendored here so the
SDK has zero dependency on private packages. Only includes structures needed
for the JSON-RPC communication protocol.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MCPError(BaseModel):
    """Error detail in an MCP response."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class MCPToolResult(BaseModel):
    """Result from a single tool execution."""

    success: bool = True
    data: dict[str, Any] | None = None
    error: MCPError | None = None
    execution_time_ms: float | None = None


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: dict[str, Any] | None = None
    error: JSONRPCError | None = None
    id: str | int | None = None


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: dict[str, Any] | None = None


class ToolContextPayload(BaseModel):
    """Schema for the ``context`` field in JSON-RPC tool call params.

    Simplified for the new SDK — no tier/extraction fields.
    """

    request_id: str = ""
    progress_callback_url: str | None = None
