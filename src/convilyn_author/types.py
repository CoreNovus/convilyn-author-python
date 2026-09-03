"""Public types for Convilyn SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolDataRef(BaseModel):
    """Reference to data stored in the ToolDataStore.

    Tools return ``{ref_id, summary}`` so the LLM context stays small.
    The agent can retrieve full data later via ``get_tool_data``.
    """

    ref_id: str
    summary: str


class ToolResult(BaseModel):
    """Result returned from a tool execution."""

    success: bool = True
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    execution_time_ms: float | None = None

    @classmethod
    def ok(cls, data: dict[str, Any]) -> ToolResult:
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, code: str, message: str, details: dict[str, Any] | None = None) -> ToolResult:
        return cls(success=False, error=ToolError(code=code, message=message, details=details))


class ToolError(BaseModel):
    """Error detail for a failed tool execution."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class ToolSpec(BaseModel):
    """Schema for a single tool in the manifest."""

    name: str
    description: str
    input_schema: dict[str, Any]
    idempotent: bool = False
    output_schema: dict[str, Any] | None = None


class ServerSpec(BaseModel):
    """Schema for the server section of a manifest."""

    name: str
    version: str
    description: str
    mcp_server_name: str | None = None


class ComplianceResult(BaseModel):
    """Result from a compliance check."""

    passed: bool
    check_name: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ComplianceReport(BaseModel):
    """Full compliance report from local testing."""

    results: list[ComplianceResult] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed(self) -> list[ComplianceResult]:
        return [r for r in self.results if not r.passed]
