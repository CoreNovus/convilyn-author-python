"""WorkflowTestRunner — local end-to-end workflow testing.

Tests a complete workflow definition locally without requiring a
platform connection. Validates tool coverage, spec compilation,
and optionally runs tools in phase order.

Usage::

    from convilyn_sdk.testing import WorkflowTestRunner

    runner = WorkflowTestRunner(workflow=workflow, tool_servers=[server])

    # Validate tool chain
    chain_result = await runner.validate_tool_chain()
    assert chain_result.valid

    # Full simulation (mock mode)
    result = await runner.run(test_input={"files": ["test.pdf"]})
    assert result.passed
"""

from __future__ import annotations

import re
import time
from typing import Any

from pydantic import BaseModel, Field

from convilyn_sdk.server import ToolServer
from convilyn_sdk.workflow import WorkflowSpec
from convilyn_sdk.workflow_validator import (
    WorkflowValidationResult,
    validate_tool_coverage,
    validate_workflow_spec,
)


class WorkflowTestResult(BaseModel):
    """Result of a workflow test run."""

    passed: bool = True
    spec_valid: bool = True
    tools_valid: bool = True
    phases_completed: list[str] = Field(default_factory=list)
    tools_invoked: list[str] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0


class WorkflowTestRunner:
    """Test a complete workflow locally.

    Args:
        workflow: WorkflowSpec instance to test.
        tool_servers: List of ToolServer instances providing the tools.
    """

    def __init__(
        self,
        workflow: WorkflowSpec,
        tool_servers: list[ToolServer],
    ) -> None:
        self._workflow = workflow
        self._servers = tool_servers
        self._compiled: dict[str, Any] | None = None

    def _compile(self) -> dict[str, Any]:
        """Compile the workflow spec (cached)."""
        if self._compiled is None:
            self._compiled = self._workflow.compile()
        return self._compiled

    async def validate_spec(self) -> WorkflowValidationResult:
        """Validate the compiled workflow spec structure."""
        return validate_workflow_spec(self._compile())

    async def validate_tool_chain(self) -> WorkflowValidationResult:
        """Verify all tools referenced in mcp_config exist in provided servers."""
        return validate_tool_coverage(self._compile(), self._servers)

    async def run(
        self,
        test_input: dict[str, Any] | None = None,
        mode: str = "mock",
    ) -> WorkflowTestResult:
        """Execute the workflow end-to-end.

        Args:
            test_input: Optional test input data (e.g., {"files": [...]}).
            mode: Execution mode.
                "mock" — calls tools in phase order with synthetic args.
                "dry_run" — validates without invoking any tools.

        Returns:
            WorkflowTestResult with pass/fail and execution details.
        """
        start = time.perf_counter()
        result = WorkflowTestResult()
        spec = self._compile()

        # Step 1: Validate spec
        spec_validation = validate_workflow_spec(spec)
        if not spec_validation.valid:
            result.spec_valid = False
            result.passed = False
            result.errors.extend(spec_validation.errors)
            result.warnings.extend(spec_validation.warnings)
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            return result
        result.warnings.extend(spec_validation.warnings)

        # Step 2: Validate tool coverage
        tool_validation = validate_tool_coverage(spec, self._servers)
        if not tool_validation.valid:
            result.tools_valid = False
            result.passed = False
            result.errors.extend(tool_validation.errors)
            result.warnings.extend(tool_validation.warnings)
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            return result
        result.warnings.extend(tool_validation.warnings)

        if mode == "dry_run":
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            return result

        # Step 3: Mock execution — call tools in phase order
        mcp_config = spec.get("mcp_config", {})
        tool_refs = mcp_config.get("tools", [])
        phases = spec.get("phases", [])

        # Build server lookup
        server_map: dict[str, ToolServer] = {s.name: s for s in self._servers}

        # Extract tool references mentioned in each phase description
        for phase in phases:
            phase_name = phase.get("phase", "")
            phase_desc = phase.get("description", "")

            # Find tool references in backticks (e.g., `server__tool_name`)
            mentioned_tools = self._extract_tool_mentions(phase_desc, tool_refs)

            for tool_ref in mentioned_tools:
                server_name, tool_name = tool_ref.split(":", 1)
                server = server_map.get(server_name)
                if not server:
                    continue

                try:
                    # Build minimal test args
                    tool_reg = server.get_tool(tool_name)
                    if tool_reg is None:
                        result.errors.append(f"Tool {tool_name} not found on server {server_name}")
                        continue

                    test_args = _build_test_args(tool_reg.input_schema)
                    tool_result = await server.call_tool(tool_name, test_args)

                    result.tools_invoked.append(tool_ref)
                    if isinstance(tool_result, dict):
                        result.outputs.append(tool_result)
                except Exception as exc:
                    result.errors.append(f"Tool {tool_ref} failed: {exc}")
                    result.passed = False

            result.phases_completed.append(phase_name)

        # If no tools were invoked but tools exist, try invoking all tools
        if not result.tools_invoked and tool_refs:
            for tool_ref in tool_refs:
                parts = tool_ref.split(":", 1)
                if len(parts) != 2:
                    continue
                server_name, tool_name = parts
                server = server_map.get(server_name)
                if not server:
                    continue

                try:
                    tool_reg = server.get_tool(tool_name)
                    if tool_reg is None:
                        continue
                    test_args = _build_test_args(tool_reg.input_schema)
                    tool_result = await server.call_tool(tool_name, test_args)
                    result.tools_invoked.append(tool_ref)
                    if isinstance(tool_result, dict):
                        result.outputs.append(tool_result)
                except Exception as exc:
                    result.errors.append(f"Tool {tool_ref} failed: {exc}")
                    result.passed = False

        if result.errors:
            result.passed = False

        result.execution_time_ms = (time.perf_counter() - start) * 1000
        return result

    @staticmethod
    def _extract_tool_mentions(
        phase_desc: str,
        tool_refs: list[str],
    ) -> list[str]:
        """Extract tool references from phase description text.

        Looks for backtick-quoted tool mentions like `server__tool_name`
        and maps them back to "server:tool" format.
        """
        # Find backtick-quoted identifiers
        mentions = re.findall(r"`([a-zA-Z0-9_]+)`", phase_desc)
        matched: list[str] = []

        for mention in mentions:
            # Convert server__tool_name → server:tool_name for matching
            for tool_ref in tool_refs:
                server, tool = tool_ref.split(":", 1)
                # Match "server__tool" or "server_tool" patterns
                normalized = f"{server.replace('-', '_')}__{tool}"
                if mention == normalized or mention == tool:
                    if tool_ref not in matched:
                        matched.append(tool_ref)
                    break

        return matched


def _build_test_args(schema: dict[str, Any]) -> dict[str, Any]:
    """Build minimal test arguments from a JSON Schema."""
    args: dict[str, Any] = {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    type_defaults: dict[str, Any] = {
        "string": "test_input",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "object": {},
        "array": [],
    }

    for name in required:
        prop = properties.get(name, {})
        prop_type = prop.get("type", "string")
        args[name] = prop.get("default", type_defaults.get(prop_type, "test"))

    return args
