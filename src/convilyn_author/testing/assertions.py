"""Test assertion helpers for Convilyn tool results."""

from __future__ import annotations

from typing import Any

from convilyn_author.types import ToolResult


def assert_tool_success(result: ToolResult, message: str = "") -> None:
    """Assert that a tool invocation succeeded."""
    if not result.success:
        error_msg = ""
        if result.error:
            error_msg = f" — {result.error.code}: {result.error.message}"
        prefix = f"{message}: " if message else ""
        raise AssertionError(f"{prefix}Tool call failed{error_msg}")


def assert_tool_error(result: ToolResult, expected_code: str | None = None) -> None:
    """Assert that a tool invocation failed with an optional error code."""
    if result.success:
        raise AssertionError(f"Expected tool failure but got success: {result.data}")
    if expected_code and result.error and result.error.code != expected_code:
        raise AssertionError(f"Expected error code '{expected_code}' but got '{result.error.code}'")


def assert_schema_valid(data: dict[str, Any], required_keys: list[str]) -> None:
    """Assert that a result dict contains all required keys."""
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise AssertionError(f"Missing required keys: {missing}")
