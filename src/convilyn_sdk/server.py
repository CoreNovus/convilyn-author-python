"""ToolServer — the developer-facing entry point for Convilyn SDK.

Developers use ``@server.tool`` to wrap any Python code (libraries, APIs,
ML models) as platform tools. The SDK handles all MCP protocol, Gateway
routing, and deployment details behind the scenes.

Usage::

    server = ToolServer(
        name="my-analyzer",
        description="Document analysis tools",
    )

    @server.tool(description="Analyze document structure")
    async def analyze(text: str, language: str = "en") -> dict:
        result = my_library.analyze(text, lang=language)
        ref_id = await server.data_store.store(result)
        return {"ref_id": ref_id, "summary": f"{len(result)} items found"}

    if __name__ == "__main__":
        server.run()
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import logging
import types as builtin_types
import typing
from collections.abc import Callable
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from convilyn_sdk.config import SDKConfig
from convilyn_sdk.context import ToolContext, create_tool_context
from convilyn_sdk.data_store import DataStoreProtocol, create_data_store
from convilyn_sdk.manifest import ConvilynManifest
from convilyn_sdk.types import ServerSpec, ToolSpec

logger = logging.getLogger("convilyn_sdk")


def _is_tool_context_param(param: inspect.Parameter) -> bool:
    """Check if a parameter is typed as ToolContext."""
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False
    if annotation is ToolContext:
        return True
    if isinstance(annotation, str) and annotation == "ToolContext":
        return True
    return False


def _build_input_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Derive JSON Schema from function signature via type hints.

    Supports: str, int, float, bool, dict, list, Optional[T], T | None,
    list[str], dict[str, Any], Literal["a", "b"], Enum subclasses,
    and Pydantic BaseModel subclasses. Skips ``self``, ``cls``, and
    ``ToolContext`` parameters.
    """
    sig = inspect.signature(func)
    hints = typing.get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if _is_tool_context_param(param):
            continue

        annotation = hints.get(name, param.annotation)
        prop = _annotation_to_json_schema(annotation)

        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(name)

        properties[name] = prop

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _annotation_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema property."""
    simple_map: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }

    if annotation in simple_map:
        return {"type": simple_map[annotation]}

    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[T] / T | None
    if _is_optional(annotation):
        inner = _unwrap_optional(annotation)
        inner_schema = _annotation_to_json_schema(inner)
        return {"anyOf": [inner_schema, {"type": "null"}]}

    # Literal["a", "b", "c"]
    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    # list[T]
    if origin is list:
        if args:
            return {"type": "array", "items": _annotation_to_json_schema(args[0])}
        return {"type": "array"}

    # dict[str, T]
    if origin is dict:
        if len(args) >= 2:
            return {
                "type": "object",
                "additionalProperties": _annotation_to_json_schema(args[1]),
            }
        return {"type": "object"}

    # Enum subclass
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {
            "type": "string",
            "enum": [e.value for e in annotation],
        }

    # Pydantic BaseModel subclass
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.model_json_schema()

    return {"type": "string"}


def _is_optional(annotation: Any) -> bool:
    """Check if annotation is Optional[T] or T | None."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union:
        return type(None) in args

    if isinstance(annotation, builtin_types.UnionType):
        return type(None) in args

    return False


def _unwrap_optional(annotation: Any) -> Any:
    """Extract T from Optional[T] or T | None."""
    args = get_args(annotation)
    non_none = [a for a in args if a is not type(None)]
    if len(non_none) == 1:
        return non_none[0]
    return non_none[0] if non_none else str


class _ToolRegistration:
    """Internal record of a registered tool."""

    __slots__ = (
        "func",
        "name",
        "description",
        "idempotent",
        "input_schema",
        "output_schema",
        "expects_context",
    )

    def __init__(
        self,
        func: Callable[..., Any],
        name: str,
        description: str,
        idempotent: bool,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        self.func = func
        self.name = name
        self.description = description
        self.idempotent = idempotent
        self.output_schema = output_schema
        self.input_schema = _build_input_schema(func)
        self.expects_context = _func_expects_context(func)


def _func_expects_context(func: Callable[..., Any]) -> bool:
    """Check if the function's first non-self parameter is ToolContext."""
    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        return _is_tool_context_param(param)
    return False


class ToolServer:
    """Define a tool server for the Convilyn AI workflow platform.

    Wraps any Python code — libraries, APIs, ML models — as platform tools.
    The SDK handles MCP protocol, data storage, and deployment details.

    Usage::

        server = ToolServer(
            name="my-tools",
            description="My custom tools",
        )

        @server.tool(description="Process text")
        async def process(text: str) -> dict:
            result = my_library.process(text)
            ref_id = await server.data_store.store(result)
            return {"ref_id": ref_id, "summary": f"Processed {len(text)} chars"}

        if __name__ == "__main__":
            server.run()
    """

    def __init__(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        capabilities: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.capabilities = list(capabilities or [])
        self._tools: list[_ToolRegistration] = []
        self._config = SDKConfig.from_env()
        self._data_store: DataStoreProtocol | None = None

    # ── Data Store ─────────────────────────────────────────────────

    @property
    def data_store(self) -> DataStoreProtocol:
        """Lazy-initialized data store for tool results.

        Local dev → InMemoryDataStore (zero AWS deps).
        Lambda → DynamoDataStore.
        """
        if self._data_store is None:
            self._data_store = create_data_store(self._config)
        return self._data_store

    # ── Tool Registration ──────────────────────────────────────────

    def tool(
        self,
        description: str,
        *,
        name: str | None = None,
        idempotent: bool = False,
        output_schema: type[BaseModel] | None = None,
    ) -> Callable[..., Any]:
        """Register a tool on this server.

        Args:
            description: Human-readable description for the AI agent.
            name: Override the function name as the tool name.
            idempotent: Whether calling this tool multiple times is safe.
            output_schema: Optional Pydantic model describing the response shape.
        """
        output_schema_dict: dict[str, Any] | None = None
        if output_schema is not None:
            output_schema_dict = output_schema.model_json_schema()

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            reg = _ToolRegistration(
                func=func,
                name=tool_name,
                description=description,
                idempotent=idempotent,
                output_schema=output_schema_dict,
            )
            self._tools.append(reg)
            return func

        return decorator

    # ── Manifest Synthesis ─────────────────────────────────────────

    def synth(self) -> ConvilynManifest:
        """Compile this server definition into a manifest blueprint."""
        tool_specs = [
            ToolSpec(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
                idempotent=t.idempotent,
                output_schema=t.output_schema,
            )
            for t in self._tools
        ]

        return ConvilynManifest(
            server=ServerSpec(
                name=self.name,
                version=self.version,
                description=self.description,
            ),
            tools=tool_specs,
            capabilities=self.capabilities,
        )

    # ── Runtime ────────────────────────────────────────────────────

    def run(
        self,
        host: str | None = None,
        port: int | None = None,
        *,
        dev: bool = False,
    ) -> None:
        """Start the tool server (blocking).

        Delegates to the internal server runtime which wraps FastMCP.

        By default the runtime is **fail-closed**: without
        ``CONVILYN_HMAC_SECRET`` it refuses to start. Pass ``dev=True``
        (as ``convilyn-author dev`` does) to opt into INSECURE local
        development without a secret — never use this in a deployed
        environment. Setting ``CONVILYN_DEV_INSECURE=1`` has the same
        effect for a bare ``python server.py`` run.
        """
        from convilyn_sdk._internal.server_runtime import start_server

        start_server(
            server=self,
            host=host or self._config.server_host,
            port=port or self._config.server_port,
            allow_insecure=dev,
        )

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke a tool directly (used by testing framework and protocol layer)."""
        for reg in self._tools:
            if reg.name == tool_name:
                # Filter arguments to only declared schema parameters
                allowed_params = set(reg.input_schema.get("properties", {}).keys())
                filtered_args = {k: v for k, v in arguments.items() if k in allowed_params}

                # Inject ToolContext if the function expects it
                if reg.expects_context:
                    ctx = create_tool_context(
                        data_store=self.data_store,
                        context_payload=context,
                    )
                    result = reg.func(ctx, **filtered_args)
                else:
                    result = reg.func(**filtered_args)

                if asyncio.iscoroutine(result):
                    return await result
                return result
        raise ValueError(f"Tool '{tool_name}' not found on server '{self.name}'")

    # ── Introspection ──────────────────────────────────────────────

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def get_tool(self, name: str) -> _ToolRegistration | None:
        for t in self._tools:
            if t.name == name:
                return t
        return None

    def __repr__(self) -> str:
        return f"ToolServer(name={self.name!r}, version={self.version!r}, tools={self.tool_names})"


# Backward compatibility alias
ConvilynServer = ToolServer
