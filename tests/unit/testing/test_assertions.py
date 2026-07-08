"""Tests for assertion helpers in ``convilyn_sdk.testing.assertions``.

Four categories per the unit-testing skill:
  * logic       — happy paths (success/error/schema valid)
  * boundary    — empty messages / empty required-keys lists
  * error       — assertion failures raise AssertionError with the right text
  * object-state — input ToolResult / dict is read-only (never mutated)
"""

from __future__ import annotations

import pytest

from convilyn_sdk.testing.assertions import (
    assert_schema_valid,
    assert_tool_error,
    assert_tool_success,
)
from convilyn_sdk.types import ToolError, ToolResult

# ── assert_tool_success ────────────────────────────────────────────


class TestAssertToolSuccess:
    def test_passes_when_success(self) -> None:
        # logic: success result → no exception
        assert_tool_success(ToolResult(success=True))

    def test_raises_when_failure_without_error_field(self) -> None:
        # error: failed result without ``error`` still raises
        with pytest.raises(AssertionError, match="Tool call failed"):
            assert_tool_success(ToolResult(success=False))

    def test_raises_with_error_code_and_message_in_text(self) -> None:
        # error: failed result with error surfaces code + message
        result = ToolResult(
            success=False,
            error=ToolError(code="X_FAIL", message="boom"),
        )
        with pytest.raises(AssertionError, match="X_FAIL: boom"):
            assert_tool_success(result)

    def test_message_prefix_is_included_in_failure(self) -> None:
        # logic: custom message prefix shows up in the raised text
        result = ToolResult(success=False)
        with pytest.raises(AssertionError, match="my context: "):
            assert_tool_success(result, message="my context")


# ── assert_tool_error ──────────────────────────────────────────────


class TestAssertToolError:
    def test_passes_when_failed(self) -> None:
        # logic: failed result → no exception
        result = ToolResult(success=False, error=ToolError(code="X", message="m"))
        assert_tool_error(result)

    def test_raises_when_success(self) -> None:
        # error: successful result fails the "expected error" assertion
        with pytest.raises(AssertionError, match="Expected tool failure"):
            assert_tool_error(ToolResult(success=True, data={"k": "v"}))

    def test_passes_when_expected_code_matches(self) -> None:
        # logic: expected code matches → no exception
        result = ToolResult(success=False, error=ToolError(code="X", message="m"))
        assert_tool_error(result, expected_code="X")

    def test_raises_on_code_mismatch(self) -> None:
        # error: code mismatch raises with both expected + actual codes
        result = ToolResult(success=False, error=ToolError(code="ACTUAL", message="m"))
        with pytest.raises(AssertionError, match="EXPECTED.*ACTUAL"):
            assert_tool_error(result, expected_code="EXPECTED")


# ── assert_schema_valid ────────────────────────────────────────────


class TestAssertSchemaValid:
    def test_passes_when_all_keys_present(self) -> None:
        # logic: every required key is in the dict
        assert_schema_valid({"a": 1, "b": 2, "c": 3}, ["a", "b"])

    def test_passes_with_empty_required_keys(self) -> None:
        # boundary: empty required-keys list passes for any dict
        assert_schema_valid({"unrelated": 1}, [])

    def test_raises_with_missing_keys_listed(self) -> None:
        # error: missing keys are named in the assertion text
        with pytest.raises(AssertionError, match=r"Missing required keys.*\['x', 'y'\]"):
            assert_schema_valid({"a": 1}, ["a", "x", "y"])

    def test_input_dict_is_not_mutated(self) -> None:
        # object-state: assertion helper never writes to the input dict
        data = {"a": 1, "b": 2}
        snapshot = dict(data)
        assert_schema_valid(data, ["a"])
        assert data == snapshot
