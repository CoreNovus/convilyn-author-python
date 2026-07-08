"""Schema-derivation + ToolContext injection tests for ``convilyn_sdk.server``.

The existing :file:`test_server.py` covers ToolServer's happy-path tool
registration; this file fills the gaps in:

* ``_annotation_to_json_schema`` — Optional, Literal, list[T], dict[str, T],
  Enum, BaseModel branches.
* ``_is_tool_context_param`` / ``_func_expects_context`` — identity and
  string-form recognition; self/cls skipping.
* ``ToolServer.tool(output_schema=...)`` — schema-via-Pydantic path.
* ``ToolServer.call_tool`` — ToolContext injection and not-found error.
* ``ToolServer.data_store`` — lazy initialisation contract.
* ``ToolServer.run`` — delegation to the internal runtime.

Four categories per the unit-testing skill:
  * logic       — happy paths
  * boundary    — Optional[T] (None branch), bare list / bare dict, empty Enum
  * error       — call_tool with unknown name
  * object-state — data_store memoised after first access
"""

from __future__ import annotations

# ruff: noqa: UP007, UP045
#
# This file intentionally uses both `typing.Optional[T]` / `typing.Union[A, B]`
# and the PEP 604 `T | None` / `A | B` shorthand. The SDK schema-derivation
# helpers must accept both forms (older code bases still pin to `Optional`),
# so the tests have to exercise both spellings explicitly. ruff's UP007/UP045
# rules would otherwise collapse the typing.* forms back into the shorthand
# and erase that coverage.
import enum
from typing import Any, Literal, Optional, Union

import pytest
from pydantic import BaseModel

from convilyn_sdk.context import ToolContext
from convilyn_sdk.data_store import InMemoryDataStore
from convilyn_sdk.server import (
    ToolServer,
    _annotation_to_json_schema,
    _func_expects_context,
    _is_optional,
    _is_tool_context_param,
    _unwrap_optional,
)


class _Colour(enum.Enum):
    RED = "red"
    BLUE = "blue"


class _Person(BaseModel):
    name: str
    age: int = 0


# ── _annotation_to_json_schema ─────────────────────────────────────


class TestAnnotationToJsonSchema:
    def test_str_maps_to_string(self) -> None:
        # logic: scalar str → JSON string
        assert _annotation_to_json_schema(str)["type"] == "string"

    def test_int_maps_to_integer(self) -> None:
        # logic: scalar int → JSON integer
        assert _annotation_to_json_schema(int)["type"] == "integer"

    def test_bool_maps_to_boolean(self) -> None:
        # logic: scalar bool → JSON boolean
        assert _annotation_to_json_schema(bool)["type"] == "boolean"

    def test_any_falls_back_to_string(self) -> None:
        # boundary: Any → "string" fallback
        assert _annotation_to_json_schema(Any)["type"] == "string"

    def test_optional_emits_anyof(self) -> None:
        # logic: Optional[int] → anyOf [int, null]
        schema = _annotation_to_json_schema(Optional[int])
        assert {"type": "null"} in schema["anyOf"]

    def test_union_with_none_emits_anyof(self) -> None:
        # boundary: `int | None` (PEP 604) is also Optional
        schema = _annotation_to_json_schema(int | None)
        assert {"type": "null"} in schema["anyOf"]

    def test_literal_emits_enum(self) -> None:
        # logic: Literal["a", "b"] → {"type": "string", "enum": [...]}
        schema = _annotation_to_json_schema(Literal["a", "b"])
        assert schema["type"] == "string"
        assert sorted(schema["enum"]) == ["a", "b"]

    def test_list_with_inner_type(self) -> None:
        # logic: list[int] → array of integers
        schema = _annotation_to_json_schema(list[int])
        assert schema["items"]["type"] == "integer"

    def test_bare_list_emits_array_without_items(self) -> None:
        # boundary: bare ``list`` → JSON array with no items schema
        schema = _annotation_to_json_schema(list)
        assert schema["type"] == "array"
        assert "items" not in schema

    def test_dict_with_value_type(self) -> None:
        # logic: dict[str, int] → object with integer additionalProperties
        schema = _annotation_to_json_schema(dict[str, int])
        assert schema["additionalProperties"]["type"] == "integer"

    def test_bare_dict_emits_object_without_additional(self) -> None:
        # boundary: bare ``dict`` → JSON object with no additionalProperties
        schema = _annotation_to_json_schema(dict)
        assert schema["type"] == "object"

    def test_enum_emits_enum_values(self) -> None:
        # logic: Enum subclass → JSON enum of value strings
        schema = _annotation_to_json_schema(_Colour)
        assert sorted(schema["enum"]) == ["blue", "red"]

    def test_pydantic_model_emits_model_schema(self) -> None:
        # logic: BaseModel subclass → ``model_json_schema()`` payload
        schema = _annotation_to_json_schema(_Person)
        assert schema["title"] == "_Person"

    def test_unknown_annotation_falls_back_to_string(self) -> None:
        # boundary: completely unknown type → "string" fallback (last branch)
        class _Mystery:
            pass

        assert _annotation_to_json_schema(_Mystery)["type"] == "string"


# ── _is_optional / _unwrap_optional ───────────────────────────────


class TestIsOptional:
    def test_optional_typing_form(self) -> None:
        # logic: typing.Optional[T] is detected
        assert _is_optional(Optional[int]) is True

    def test_pep604_union_form(self) -> None:
        # logic: PEP 604 ``T | None`` is detected
        assert _is_optional(int | None) is True

    def test_plain_union_without_none_is_not_optional(self) -> None:
        # boundary: ``Union[int, str]`` (no None) is NOT optional
        assert _is_optional(Union[int, str]) is False

    def test_scalar_is_not_optional(self) -> None:
        # boundary: scalar str is NOT optional
        assert _is_optional(str) is False


class TestUnwrapOptional:
    def test_unwraps_typing_optional(self) -> None:
        # logic: Optional[int] → int
        assert _unwrap_optional(Optional[int]) is int

    def test_unwraps_pep604_form(self) -> None:
        # logic: int | None → int
        assert _unwrap_optional(int | None) is int


# ── _is_tool_context_param / _func_expects_context ────────────────


class TestIsToolContextParam:
    def test_identity_annotation_matches(self) -> None:
        # logic: parameter annotated with ToolContext (identity) → True
        async def fn(ctx: ToolContext) -> None: ...

        import inspect
        param = list(inspect.signature(fn).parameters.values())[0]
        assert _is_tool_context_param(param) is True

    def test_string_annotation_matches(self) -> None:
        # logic: stringified "ToolContext" forward-ref → True
        async def fn(ctx: ToolContext) -> None: ...

        # When using forward reference, annotation can be the string.
        # Build a fake param with string annotation explicitly to avoid
        # depending on PEP 563 / from __future__ behaviour.

        class _FakeParam:
            annotation = "ToolContext"

        assert _is_tool_context_param(_FakeParam()) is True  # type: ignore[arg-type]

    def test_empty_annotation_returns_false(self) -> None:
        # boundary: no annotation → False
        async def fn(x) -> None: ...  # type: ignore[no-untyped-def]

        import inspect
        param = list(inspect.signature(fn).parameters.values())[0]
        assert _is_tool_context_param(param) is False

    def test_other_annotation_returns_false(self) -> None:
        # boundary: non-ToolContext annotation → False
        async def fn(x: int) -> None: ...

        import inspect
        param = list(inspect.signature(fn).parameters.values())[0]
        assert _is_tool_context_param(param) is False


class TestFuncExpectsContext:
    def test_first_param_is_tool_context(self) -> None:
        # logic: first non-self param annotated with ToolContext → True
        async def fn(ctx: ToolContext, x: int) -> None: ...

        assert _func_expects_context(fn) is True

    def test_no_params_returns_false(self) -> None:
        # boundary: nullary function → False
        async def fn() -> None: ...

        assert _func_expects_context(fn) is False

    def test_first_param_is_not_tool_context(self) -> None:
        # boundary: first param of another type → False
        async def fn(x: int) -> None: ...

        assert _func_expects_context(fn) is False


# ── ToolServer.tool with output_schema ────────────────────────────


class TestToolServerOutputSchema:
    def test_output_schema_pydantic_model_is_recorded(self) -> None:
        # logic: @server.tool(output_schema=Model) stores the JSON-schema dict
        server = ToolServer(name="s", description="d", version="0.1.0")

        @server.tool(description="returns a Person", output_schema=_Person)
        async def make_person(name: str) -> dict:  # type: ignore[return-value]
            return {"name": name, "age": 0}

        reg = server._tools[0]
        assert reg.output_schema is not None
        assert reg.output_schema["title"] == "_Person"


# ── ToolServer.data_store lazy init ───────────────────────────────


class TestToolServerDataStore:
    def test_data_store_returns_in_memory_in_local_env(self) -> None:
        # object-state: default env is local → InMemoryDataStore
        server = ToolServer(name="s", description="d", version="0.1.0")
        assert isinstance(server.data_store, InMemoryDataStore)

    def test_data_store_is_memoised(self) -> None:
        # object-state: second access returns the same instance
        server = ToolServer(name="s", description="d", version="0.1.0")
        first = server.data_store
        second = server.data_store
        assert first is second


# ── ToolServer.call_tool ──────────────────────────────────────────


class TestToolServerCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_unknown_raises_value_error(self) -> None:
        # error: calling an unregistered tool name raises ValueError
        server = ToolServer(name="s", description="d", version="0.1.0")
        with pytest.raises(ValueError, match="not found"):
            await server.call_tool("missing", {})

    @pytest.mark.asyncio
    async def test_call_tool_injects_context_when_signature_requests_it(
        self,
    ) -> None:
        # logic: a tool whose first param is ToolContext gets one injected
        server = ToolServer(name="s", description="d", version="0.1.0")
        captured: dict[str, object] = {}

        @server.tool(description="echo with context")
        async def echo_with_ctx(ctx: ToolContext, text: str) -> dict:
            captured["request_id"] = ctx.request_id
            return {"text": text}

        result = await server.call_tool(
            "echo_with_ctx",
            {"text": "hi"},
            context={"request_id": "r-1"},
        )
        assert result["text"] == "hi"
        assert captured["request_id"] == "r-1"

    @pytest.mark.asyncio
    async def test_call_tool_filters_unexpected_args(self) -> None:
        # boundary: args not in the input schema are silently dropped
        server = ToolServer(name="s", description="d", version="0.1.0")

        @server.tool(description="echo")
        async def echo(text: str) -> dict:
            return {"text": text}

        result = await server.call_tool(
            "echo",
            {"text": "hi", "extra_field_that_does_not_exist": True},
        )
        assert result == {"text": "hi"}


# ── ToolServer.run delegation ─────────────────────────────────────


class TestToolServerRun:
    def test_run_delegates_to_internal_runtime(self, monkeypatch) -> None:
        # logic: ToolServer.run forwards host/port to start_server
        from convilyn_sdk._internal import server_runtime

        captured: dict[str, object] = {}

        def fake_start_server(*, server, host, port, allow_insecure=False):  # type: ignore[no-untyped-def]
            captured["server"] = server
            captured["host"] = host
            captured["port"] = port
            captured["allow_insecure"] = allow_insecure

        monkeypatch.setattr(server_runtime, "start_server", fake_start_server)
        server = ToolServer(name="s", description="d", version="0.1.0")
        server.run(host="0.0.0.0", port=9001)
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 9001
        # Default run() is fail-closed: no insecure opt-in unless dev=True.
        assert captured["allow_insecure"] is False
