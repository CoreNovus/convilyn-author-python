"""Convilyn JSON-RPC 2.0 protocol adapter.

Translates between the Gateway's JSON-RPC protocol and the developer's
tool functions. Also auto-registers the ``get_tool_data`` tool for
DataStore retrieval.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from convilyn_sdk._internal.models import (
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPError,
    MCPToolResult,
)

logger = logging.getLogger("convilyn_sdk._internal.protocol")

# JSON-RPC error codes
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _is_dev_mode() -> bool:
    """Check if running in dev mode (localhost)."""
    host = os.environ.get("CONVILYN_HOST", "127.0.0.1")
    return host in ("127.0.0.1", "localhost", "0.0.0.0")


async def handle_jsonrpc_request(
    request: JSONRPCRequest,
    tool_handler: Any,
) -> JSONRPCResponse:
    """Process an incoming JSON-RPC request and dispatch to the appropriate tool."""
    if request.method != "tools/call":
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=METHOD_NOT_FOUND,
                message=f"Method '{request.method}' not supported",
            ),
        )

    tool_name = request.params.get("name", "")
    arguments = request.params.get("arguments", {})
    context = request.params.get("context", {})

    if not tool_name:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=INVALID_PARAMS,
                message="Missing 'name' in params",
            ),
        )

    # Handle built-in get_tool_data tool
    if tool_name == "get_tool_data":
        return await _handle_get_tool_data(request, tool_handler, arguments)

    tool_reg = tool_handler.get_tool(tool_name)
    if tool_reg is None:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=METHOD_NOT_FOUND,
                message=f"Tool '{tool_name}' not found",
            ),
        )

    start = time.monotonic()
    try:
        raw_result = await tool_handler.call_tool(tool_name, arguments, context=context)
        elapsed_ms = (time.monotonic() - start) * 1000

        if isinstance(raw_result, dict):
            data = raw_result
        else:
            data = {"value": raw_result}

        tool_result = MCPToolResult(
            success=True,
            data=data,
            execution_time_ms=round(elapsed_ms, 2),
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        # logger.exception logs the traceback in our process logs without
        # exposing it over the wire — even in dev mode the SDK now returns
        # only exception type + message to the caller.
        logger.exception("Tool '%s' failed", tool_name)

        if _is_dev_mode():
            error_message = f"Tool '{tool_name}' execution failed: {type(exc).__name__}: {exc}"
            error_details: dict[str, Any] | None = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
        else:
            error_message = f"Tool '{tool_name}' execution failed"
            error_details = None

        tool_result = MCPToolResult(
            success=False,
            error=MCPError(
                code="EXECUTION_ERROR",
                message=error_message,
                details=error_details,
            ),
            execution_time_ms=round(elapsed_ms, 2),
        )

    return JSONRPCResponse(
        id=request.id,
        result=tool_result.model_dump(),
    )


async def _handle_get_tool_data(
    request: JSONRPCRequest,
    tool_handler: Any,
    arguments: dict[str, Any],
) -> JSONRPCResponse:
    """Handle the auto-registered get_tool_data tool."""
    ref_id = arguments.get("ref_id", "")
    if not ref_id:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=INVALID_PARAMS,
                message="Missing 'ref_id' in arguments",
            ),
        )

    try:
        data = await tool_handler.data_store.get(ref_id)
        if data is None:
            tool_result = MCPToolResult(
                success=False,
                error=MCPError(
                    code="NOT_FOUND",
                    message=f"No data found for ref_id '{ref_id}'",
                ),
            )
        else:
            tool_result = MCPToolResult(success=True, data=data)
    except Exception as exc:
        logger.error("get_tool_data failed: %s", exc)
        tool_result = MCPToolResult(
            success=False,
            error=MCPError(code="INTERNAL_ERROR", message=str(exc)),
        )

    return JSONRPCResponse(
        id=request.id,
        result=tool_result.model_dump(),
    )


def parse_jsonrpc_request(body: dict[str, Any]) -> JSONRPCRequest:
    """Parse and validate a JSON-RPC 2.0 request body."""
    return JSONRPCRequest.model_validate(body)
