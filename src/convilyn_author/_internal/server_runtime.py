"""HTTP server runtime — wraps FastMCP for MCP-compatible tool serving.

Produces an HTTP server that is protocol-compatible with internal MCP
servers. Inbound POST /mcp requests are HMAC-verified against the
gateway's signature (see ``convilyn_author._internal.auth``).

Signature verification is **fail-closed**: a server with no
``CONVILYN_HMAC_SECRET`` refuses to start and rejects ``/mcp`` requests
unless the operator *explicitly* opts into insecure local development —
either by running ``convilyn-author dev`` (which passes ``dev=True``
through ``ToolServer.run``) or by setting ``CONVILYN_DEV_INSECURE=1`` for
a bare ``python server.py`` run. The ambient ``CONVILYN_ENVIRONMENT`` /
bind-host are NOT used as an auth signal — a deployment that simply
forgets to set the secret must fail loudly, not serve open.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import uvicorn

from convilyn_author._internal.auth import (
    InvalidSignatureError,
    verify_signature,
)
from convilyn_author._internal.protocol import handle_jsonrpc_request, parse_jsonrpc_request
from convilyn_author.config import SDKConfig

if TYPE_CHECKING:
    from convilyn_author.server import ToolServer

logger = logging.getLogger("convilyn_author._internal.server_runtime")

MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

# Environment variable that explicitly opts a bare ``python server.py`` run
# into INSECURE local development (no inbound signature verification). The
# ``convilyn-author dev`` CLI sets ``dev=True`` directly and does not need
# this; it exists for the ad-hoc ``python server.py`` local path.
ENV_DEV_INSECURE = "CONVILYN_DEV_INSECURE"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class ConvilynStartupError(RuntimeError):
    """Raised when the server cannot safely start (e.g. prod without HMAC secret)."""


def _dev_insecure_requested() -> bool:
    """Return True iff the operator explicitly opted into insecure local dev.

    Reads :data:`ENV_DEV_INSECURE`; any other value (including unset) is
    treated as "not opted in" so the secure default is fail-closed.
    """
    return os.environ.get(ENV_DEV_INSECURE, "").strip().lower() in _TRUTHY


def _headers_to_dict(raw_headers: list[tuple[bytes, bytes]] | None) -> dict[str, str]:
    """Lower-case ASGI header tuples into a {name: value} dict."""
    if not raw_headers:
        return {}
    return {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in raw_headers}


def _create_asgi_app(
    server: ToolServer,
    config: SDKConfig | None = None,
    *,
    allow_insecure: bool = False,
) -> Any:
    """Build a minimal ASGI application for the tool server.

    Endpoints:
        GET  /health    — Health check
        GET  /manifest  — Compiled manifest blueprint
        POST /mcp       — JSON-RPC tool invocation (HMAC-verified)

    ``allow_insecure`` permits serving ``/mcp`` without a configured HMAC
    secret — INSECURE, for explicit local development only. It defaults to
    ``False`` so the app fails closed: with no secret and no opt-in, every
    ``/mcp`` request is rejected with 401.
    """
    cfg = config or SDKConfig.from_env()
    manifest = server.synth()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await receive()
            await send({"type": "lifespan.startup.complete"})
            await receive()
            await send({"type": "lifespan.shutdown.complete"})
            return

        if scope["type"] != "http":
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path == "/health" and method == "GET":
            await _send_json(
                send,
                200,
                {
                    "status": "healthy",
                    "server": server.name,
                    "version": server.version,
                    "tool_count": len(server.tool_names),
                },
            )
            return

        if path == "/manifest" and method == "GET":
            await _send_json(send, 200, manifest.to_dict())
            return

        if path == "/mcp" and method == "POST":
            body = await _read_body(receive)
            headers = _headers_to_dict(scope.get("headers"))

            if not _authorize_request(
                cfg,
                body,
                headers,
                server_name=server.name,
                allow_insecure=allow_insecure,
            ):
                await _send_json(
                    send,
                    401,
                    {
                        "code": "INVALID_SIGNATURE",
                        "message": "Request signature could not be verified",
                    },
                )
                return

            try:
                request_data = json.loads(body)
                rpc_request = parse_jsonrpc_request(request_data)
                response = await handle_jsonrpc_request(rpc_request, server)
                await _send_json(send, 200, response.model_dump())
            except json.JSONDecodeError:
                await _send_json(send, 400, {"error": "Invalid JSON"})
            except Exception:
                logger.exception("Request handling failed")
                await _send_json(send, 500, {"error": "Internal server error"})
            return

        await _send_json(send, 404, {"error": "Not found"})

    return app


def _authorize_request(
    cfg: SDKConfig,
    body: bytes,
    headers: dict[str, str],
    *,
    server_name: str,
    allow_insecure: bool = False,
) -> bool:
    """Verify the inbound HMAC signature for POST /mcp.

    Returns True if the request should proceed; False if it must be
    rejected with 401. **Fail-closed**: with no configured secret we
    reject the request unless ``allow_insecure`` is set (explicit local
    development). The ambient environment / bind-host are deliberately
    NOT consulted — a deployment that forgets the secret must reject, not
    silently serve open.
    """
    if not cfg.hmac_secret:
        if allow_insecure:
            logger.warning(
                "CONVILYN_HMAC_SECRET not set; serving /mcp WITHOUT signature "
                "verification (insecure local dev only — do NOT deploy this "
                "configuration)",
            )
            return True
        logger.error(
            "CONVILYN_HMAC_SECRET missing and insecure dev not opted in; "
            "rejecting unsigned /mcp request for server '%s'",
            server_name,
        )
        return False

    try:
        verify_signature(
            secret=cfg.hmac_secret,
            body=body,
            headers=headers,
            tolerance_seconds=cfg.hmac_tolerance_seconds,
        )
    except InvalidSignatureError as exc:
        logger.warning(
            "HMAC verification failed for server '%s': reason=%s",
            server_name,
            exc.reason,
        )
        return False
    return True


async def _read_body(receive: Any) -> bytes:
    """Read the full request body from ASGI receive (max 10 MB)."""
    chunks: list[bytes] = []
    total_size = 0
    while True:
        msg = await receive()
        chunk = msg.get("body", b"")
        total_size += len(chunk)
        if total_size > MAX_BODY_SIZE:
            raise ValueError("Request body too large")
        chunks.append(chunk)
        if not msg.get("more_body", False):
            break
    return b"".join(chunks)


async def _send_json(send: Any, status: int, data: dict[str, Any]) -> None:
    """Send a JSON HTTP response with security headers."""
    body = json.dumps(data).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode("utf-8")],
                [b"x-content-type-options", b"nosniff"],
                [b"x-frame-options", b"DENY"],
                [b"cache-control", b"no-store"],
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )


def start_server(
    server: ToolServer,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    allow_insecure: bool = False,
) -> None:
    """Start the tool server with uvicorn.

    **Fail-closed:** unless ``CONVILYN_HMAC_SECRET`` is set, the server
    refuses to start with ``ConvilynStartupError`` — independent of
    ``CONVILYN_ENVIRONMENT`` or the bind host. Insecure local development
    must be opted into explicitly, either via ``allow_insecure=True``
    (passed by ``ToolServer.run(dev=True)`` / ``convilyn-author dev``) or
    by setting ``CONVILYN_DEV_INSECURE=1``.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    cfg = SDKConfig.from_env()
    insecure = allow_insecure or _dev_insecure_requested()
    if not cfg.hmac_secret and not insecure:
        raise ConvilynStartupError(
            "CONVILYN_HMAC_SECRET is required to serve inbound /mcp traffic. "
            "Refusing to start without signature verification. For local "
            "development use `convilyn-author dev` or set "
            f"{ENV_DEV_INSECURE}=1 (INSECURE — local only)."
        )

    logger.info("Starting ToolServer '%s' on %s:%d", server.name, host, port)
    logger.info("Tools: %s", ", ".join(server.tool_names))
    if cfg.hmac_secret:
        logger.info("HMAC verification: ENABLED")
    else:
        logger.warning("HMAC verification: DISABLED (insecure local dev mode)")

    app = _create_asgi_app(server, cfg, allow_insecure=insecure)
    uvicorn.run(app, host=host, port=port, log_level="info")
