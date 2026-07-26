"""Local test runner — validates tools offline without external services."""

from __future__ import annotations

import logging
import time
from typing import Any

from convilyn_author.types import ComplianceReport, ComplianceResult, ToolResult

logger = logging.getLogger("convilyn_author.testing.runner")


class ConvilynTestRunner:
    """Run local validation on a ToolServer.

    Works entirely offline — no API calls needed.

    Usage::

        runner = ConvilynTestRunner(server=my_server)
        result = await runner.call_tool("get_weather", {"location": "Tokyo"})
        assert result.success
        report = await runner.run_compliance_check()
        assert report.all_passed
    """

    def __init__(self, server: Any) -> None:
        self._server = server

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool and wrap the result in a ToolResult."""
        start = time.monotonic()
        try:
            raw = await self._server.call_tool(tool_name, arguments)
            elapsed = (time.monotonic() - start) * 1000

            if isinstance(raw, dict):
                data = raw
            else:
                data = {"value": raw}

            return ToolResult(
                success=True,
                data=data,
                execution_time_ms=round(elapsed, 2),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult.fail(
                code="EXECUTION_ERROR",
                message=str(exc),
            )

    async def run_compliance_check(self) -> ComplianceReport:
        """Run all compliance checks against the server."""
        results: list[ComplianceResult] = []

        results.append(self._check_server_metadata())
        results.append(self._check_tools_exist())
        results.extend(self._check_tool_schemas())
        results.append(self._check_manifest_synth())
        results.extend(await self._check_tool_invocations())
        results.extend(await self._check_ref_id_pattern())
        results.append(self._check_get_tool_data())

        return ComplianceReport(results=results)

    def _check_server_metadata(self) -> ComplianceResult:
        """Verify server has required metadata."""
        issues: list[str] = []
        if not self._server.name:
            issues.append("Server name is empty")
        if not self._server.description:
            issues.append("Server description is empty")
        if not self._server.version:
            issues.append("Server version is empty")

        if issues:
            return ComplianceResult(
                passed=False,
                check_name="server_metadata",
                message=f"Missing metadata: {', '.join(issues)}",
            )
        return ComplianceResult(
            passed=True,
            check_name="server_metadata",
            message="Server metadata is complete",
        )

    def _check_tools_exist(self) -> ComplianceResult:
        """Verify server has at least one tool."""
        if not self._server.tool_names:
            return ComplianceResult(
                passed=False,
                check_name="tools_exist",
                message="Server has no tools registered",
            )
        return ComplianceResult(
            passed=True,
            check_name="tools_exist",
            message=f"Server has {len(self._server.tool_names)} tool(s)",
        )

    def _check_tool_schemas(self) -> list[ComplianceResult]:
        """Verify each tool has a valid input schema."""
        results: list[ComplianceResult] = []
        for name in self._server.tool_names:
            tool = self._server.get_tool(name)
            if tool is None:
                results.append(
                    ComplianceResult(
                        passed=False,
                        check_name=f"tool_schema:{name}",
                        message=f"Tool '{name}' registration not found",
                    )
                )
                continue

            schema = tool.input_schema
            if not isinstance(schema, dict) or "type" not in schema:
                results.append(
                    ComplianceResult(
                        passed=False,
                        check_name=f"tool_schema:{name}",
                        message=f"Tool '{name}' has invalid input schema",
                    )
                )
                continue

            if not tool.description:
                results.append(
                    ComplianceResult(
                        passed=False,
                        check_name=f"tool_schema:{name}",
                        message=f"Tool '{name}' is missing a description",
                    )
                )
                continue

            results.append(
                ComplianceResult(
                    passed=True,
                    check_name=f"tool_schema:{name}",
                    message=f"Tool '{name}' schema is valid",
                )
            )
        return results

    def _check_manifest_synth(self) -> ComplianceResult:
        """Verify manifest can be synthesized."""
        try:
            manifest = self._server.synth()
            json_str = manifest.to_json()
            if not json_str:
                return ComplianceResult(
                    passed=False,
                    check_name="manifest_synth",
                    message="Manifest synth produced empty output",
                )
            return ComplianceResult(
                passed=True,
                check_name="manifest_synth",
                message="Manifest synthesized successfully",
                details={"tools_count": len(manifest.tools)},
            )
        except Exception as exc:
            return ComplianceResult(
                passed=False,
                check_name="manifest_synth",
                message=f"Manifest synth failed: {exc}",
            )

    async def _check_tool_invocations(self) -> list[ComplianceResult]:
        """Verify tools can be invoked without crashing (dry-run with empty args)."""
        results: list[ComplianceResult] = []
        for name in self._server.tool_names:
            tool = self._server.get_tool(name)
            if tool is None:
                continue

            schema = tool.input_schema
            required = schema.get("required", [])
            if required:
                results.append(
                    ComplianceResult(
                        passed=True,
                        check_name=f"tool_invocation:{name}",
                        message=f"Tool '{name}' skipped (has required params)",
                        details={"required": required},
                    )
                )
            else:
                try:
                    await self._server.call_tool(name, {})
                    results.append(
                        ComplianceResult(
                            passed=True,
                            check_name=f"tool_invocation:{name}",
                            message=f"Tool '{name}' invoked successfully with defaults",
                        )
                    )
                except Exception as exc:
                    results.append(
                        ComplianceResult(
                            passed=False,
                            check_name=f"tool_invocation:{name}",
                            message=f"Tool '{name}' crashed with defaults: {exc}",
                        )
                    )
        return results

    async def _check_ref_id_pattern(self) -> list[ComplianceResult]:
        """Check if tools return {ref_id, summary} pattern (warning, not fail)."""
        results: list[ComplianceResult] = []
        for name in self._server.tool_names:
            tool = self._server.get_tool(name)
            if tool is None:
                continue

            schema = tool.input_schema
            required = schema.get("required", [])
            if required:
                continue

            try:
                raw = await self._server.call_tool(name, {})
                if isinstance(raw, dict):
                    has_ref = "ref_id" in raw
                    has_summary = "summary" in raw
                    if has_ref and has_summary:
                        results.append(
                            ComplianceResult(
                                passed=True,
                                check_name=f"ref_id_pattern:{name}",
                                message=f"Tool '{name}' returns ref_id + summary",
                            )
                        )
                    else:
                        results.append(
                            ComplianceResult(
                                passed=True,  # warning, not fail
                                check_name=f"ref_id_pattern:{name}",
                                message=(
                                    f"Tool '{name}' does not return ref_id+summary "
                                    "(recommended for large results)"
                                ),
                            )
                        )
            except Exception:
                pass
        return results

    def _check_get_tool_data(self) -> ComplianceResult:
        """Verify data_store is accessible (get_tool_data auto-registered)."""
        try:
            store = self._server.data_store
            if store is not None:
                return ComplianceResult(
                    passed=True,
                    check_name="get_tool_data",
                    message="DataStore is available (get_tool_data auto-registered)",
                )
            return ComplianceResult(
                passed=False,
                check_name="get_tool_data",
                message="DataStore is not initialized",
            )
        except Exception as exc:
            return ComplianceResult(
                passed=False,
                check_name="get_tool_data",
                message=f"DataStore check failed: {exc}",
            )
