"""HMAC inbound-signature verification tests.

Four categories per the unit-testing skill:
  * logic       — happy path: a correctly-signed request reaches the tool
  * boundary    — timestamp tolerance edges
  * error       — tampered body / missing header / wrong secret → 401
  * object-state — dev no-secret allow + prod no-secret startup refusal
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace
from typing import Any

import pytest

from convilyn_author._internal.auth import (
    InvalidSignatureError,
    verify_signature,
)
from convilyn_author._internal.server_runtime import (
    ConvilynStartupError,
    _create_asgi_app,
    start_server,
)
from convilyn_author.config import SDKConfig
from convilyn_author.server import ToolServer

# ── Helpers ──────────────────────────────────────────────────────────


def _make_server() -> ToolServer:
    server = ToolServer(name="hmac-srv", description="HMAC test server")

    @server.tool(description="Echo")
    async def echo(message: str) -> dict:
        return {"echo": message}

    return server


def _sign(secret: str, body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(timestamp if timestamp is not None else time.time()))
    message = ts.encode("utf-8") + b"." + body
    sig = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "X-Convilyn-Signature": sig,
        "X-Convilyn-Timestamp": ts,
        "X-Convilyn-Server-Id": "hmac-srv",
    }


def _headers_to_asgi(headers: dict[str, str]) -> list[tuple[bytes, bytes]]:
    return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]


async def _simulate_request(
    app: Any,
    method: str,
    path: str,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict[str, Any]]:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
    }
    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"body": body, "more_body": False}
        return {"body": b"", "more_body": False}

    status_code = 0
    response_body = b""

    async def send(msg: dict[str, Any]) -> None:
        nonlocal status_code, response_body
        if msg["type"] == "http.response.start":
            status_code = msg["status"]
        elif msg["type"] == "http.response.body":
            response_body = msg.get("body", b"")

    await app(scope, receive, send)
    return status_code, json.loads(response_body) if response_body else {}


def _valid_call_body() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "hi"}},
        }
    ).encode("utf-8")


# ── 1. Logic — happy path ────────────────────────────────────────────


class TestHmacLogic:
    """Valid signature reaches the tool handler and returns the tool result."""

    @pytest.mark.asyncio
    async def test_valid_signature_invokes_tool(self):
        cfg = SDKConfig(
            environment="production",
            hmac_secret="shared-secret-32-bytes-long",  # pragma: allowlist secret
        )
        app = _create_asgi_app(_make_server(), cfg)
        body = _valid_call_body()

        status, data = await _simulate_request(
            app,
            "POST",
            "/mcp",
            body=body,
            headers=_headers_to_asgi(_sign(cfg.hmac_secret, body)),
        )

        assert status == 200
        assert data["result"]["success"] is True
        assert data["result"]["data"] == {"echo": "hi"}


# ── 2. Boundary — timestamp tolerance edges ──────────────────────────


class TestHmacBoundary:
    """Verifier accepts within tolerance and rejects just outside it."""

    def test_timestamp_at_tolerance_edge_passes(self):
        secret = "secret"  # pragma: allowlist secret
        body = b'{"ok": true}'
        now = 1_700_000_000.0
        # Exactly at the edge of the tolerance window: |now - ts| == 300
        ts = int(now) - 300
        sig = hmac.new(
            secret.encode(),
            f"{ts}".encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()

        verify_signature(
            secret=secret,
            body=body,
            headers={
                "x-convilyn-signature": sig,
                "x-convilyn-timestamp": str(ts),
            },
            tolerance_seconds=300,
            now=now,
        )  # must not raise

    def test_timestamp_just_outside_tolerance_rejects(self):
        secret = "secret"  # pragma: allowlist secret
        body = b'{"ok": true}'
        now = 1_700_000_000.0
        ts = int(now) - 301  # one second past tolerance
        sig = hmac.new(
            secret.encode(),
            f"{ts}".encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()

        with pytest.raises(InvalidSignatureError) as info:
            verify_signature(
                secret=secret,
                body=body,
                headers={
                    "x-convilyn-signature": sig,
                    "x-convilyn-timestamp": str(ts),
                },
                tolerance_seconds=300,
                now=now,
            )
        assert info.value.reason == "timestamp_out_of_range"


# ── 3. Error — tampered body / missing header / wrong secret ─────────


class TestHmacErrors:
    """Anything other than an exact match must reject with 401."""

    @pytest.mark.asyncio
    async def test_tampered_body_rejected(self):
        cfg = SDKConfig(environment="production", hmac_secret="secret")  # pragma: allowlist secret
        app = _create_asgi_app(_make_server(), cfg)
        original = _valid_call_body()
        signed = _sign(cfg.hmac_secret, original)
        tampered = original.replace(b'"hi"', b'"evil"')

        status, data = await _simulate_request(
            app,
            "POST",
            "/mcp",
            body=tampered,
            headers=_headers_to_asgi(signed),
        )

        assert status == 401
        assert data["code"] == "INVALID_SIGNATURE"

    @pytest.mark.asyncio
    async def test_missing_signature_header_rejected(self):
        cfg = SDKConfig(environment="production", hmac_secret="secret")  # pragma: allowlist secret
        app = _create_asgi_app(_make_server(), cfg)
        body = _valid_call_body()

        status, data = await _simulate_request(
            app,
            "POST",
            "/mcp",
            body=body,
            headers=_headers_to_asgi({"X-Convilyn-Timestamp": str(int(time.time()))}),
        )

        assert status == 401
        assert data["code"] == "INVALID_SIGNATURE"

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self):
        cfg = SDKConfig(
            environment="production",
            hmac_secret="real-secret",  # pragma: allowlist secret
        )
        app = _create_asgi_app(_make_server(), cfg)
        body = _valid_call_body()

        status, data = await _simulate_request(
            app,
            "POST",
            "/mcp",
            body=body,
            headers=_headers_to_asgi(_sign("attacker-secret", body)),
        )

        assert status == 401
        assert data["code"] == "INVALID_SIGNATURE"


# ── 4. Object-state — dev allow / prod refuse to boot ────────────────


class TestHmacObjectState:
    """Dev mode is forgiving; production is fail-fast."""

    @pytest.mark.asyncio
    async def test_explicit_insecure_no_secret_accepts_request(self, caplog):
        # Explicit insecure-dev opt-in (allow_insecure=True) accepts unsigned
        # requests. Note: a "local" environment alone NO LONGER bypasses auth —
        # see test_security.py::TestInboundAuthFailClosed.
        cfg = SDKConfig(environment="local", server_host="127.0.0.1", hmac_secret=None)
        app = _create_asgi_app(_make_server(), cfg, allow_insecure=True)
        body = _valid_call_body()

        status, data = await _simulate_request(
            app,
            "POST",
            "/mcp",
            body=body,
            headers=[],
        )

        assert status == 200
        assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_local_env_no_optin_now_rejects(self):
        # Regression guard for the fail-open fix: environment="local" without
        # an explicit opt-in must reject unsigned requests.
        cfg = SDKConfig(environment="local", server_host="127.0.0.1", hmac_secret=None)
        app = _create_asgi_app(_make_server(), cfg)
        status, _ = await _simulate_request(
            app, "POST", "/mcp", body=_valid_call_body(), headers=[]
        )
        assert status == 401

    def test_prod_mode_no_secret_refuses_to_start(self, monkeypatch):
        # Build a prod-like env: non-local environment, no secret, non-local host
        env = {
            "CONVILYN_ENVIRONMENT": "production",
            "CONVILYN_HOST": "0.0.0.0",
            "AWS_LAMBDA_FUNCTION_NAME": "convilyn-tool-srv",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)

        # SDKConfig.from_env() reads at call time; verify our preconditions.
        cfg = SDKConfig.from_env()
        assert cfg.hmac_secret is None
        assert cfg.is_local is False

        with pytest.raises(ConvilynStartupError):
            start_server(_make_server(), host="0.0.0.0", port=8080)

    def test_replace_helper_keeps_config_immutable(self):
        # SDKConfig is frozen; replace() must produce a new instance.
        a = SDKConfig(hmac_secret=None)
        b = replace(a, hmac_secret="x")
        assert a.hmac_secret is None
        assert b.hmac_secret == "x"
