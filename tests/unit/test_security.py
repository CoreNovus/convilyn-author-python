"""Security-focused tests for hardening fixes.

Covers: path traversal prevention, security headers, health endpoint info
hiding, argument filtering, scaffold name validation, config defaults,
generic error messages.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from convilyn_sdk._internal.server_runtime import (
    _create_asgi_app,
    _read_body,
)
from convilyn_sdk.cli.main import _load_server_from_file
from convilyn_sdk.cli.scaffold import scaffold_project
from convilyn_sdk.config import SDKConfig
from convilyn_sdk.server import ToolServer

# ── Helpers ──────────────────────────────────────────────────────────


def _make_server(**overrides: Any) -> ToolServer:
    """Create a test server with a single echo tool."""
    kwargs: dict[str, Any] = {
        "name": "test-srv",
        "description": "Test server",
        "version": "0.1.0",
    }
    kwargs.update(overrides)
    server = ToolServer(**kwargs)

    @server.tool(description="Echo input")
    async def echo(message: str) -> dict:
        return {"echo": message}

    @server.tool(description="Tool that fails")
    async def fail_tool(reason: str) -> dict:
        raise RuntimeError(reason)

    return server


async def _simulate_request(
    app: Any,
    method: str,
    path: str,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict[str, Any], list[tuple[bytes, bytes]]]:
    """Simulate an ASGI HTTP request and capture the response."""
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

    response_started = False
    status_code = 0
    response_headers: list[tuple[bytes, bytes]] = []
    response_body = b""

    async def send(msg: dict[str, Any]) -> None:
        nonlocal response_started, status_code, response_headers, response_body
        if msg["type"] == "http.response.start":
            response_started = True
            status_code = msg["status"]
            response_headers = [(h[0], h[1]) for h in msg.get("headers", [])]
        elif msg["type"] == "http.response.body":
            response_body = msg.get("body", b"")

    await app(scope, receive, send)
    data = json.loads(response_body) if response_body else {}
    return status_code, data, response_headers


# ══════════════════════════════════════════════════════════════════════
# 1. CLI: _load_server_from_file — CWD restriction + .py extension
# ══════════════════════════════════════════════════════════════════════


class TestFileLoadingSecurity:
    """Verify that _load_server_from_file restricts to cwd and .py files."""

    def test_rejects_file_outside_cwd(self, tmp_path, monkeypatch):
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        server_file = outside_dir / "server.py"
        server_file.write_text(
            'from convilyn_sdk import ToolServer\nserver = ToolServer(name="t", description="t")\n'
        )

        cwd = tmp_path / "project"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        with pytest.raises(SystemExit):
            _load_server_from_file(str(server_file))

    def test_rejects_dotdot_traversal(self, tmp_path, monkeypatch):
        cwd = tmp_path / "project" / "sub"
        cwd.mkdir(parents=True)
        monkeypatch.chdir(cwd)

        server_file = tmp_path / "evil.py"
        server_file.write_text("x = 1")

        with pytest.raises(SystemExit):
            _load_server_from_file("../../evil.py")

    def test_rejects_non_py_extension(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        txt_file = tmp_path / "server.txt"
        txt_file.write_text("not python")

        with pytest.raises(SystemExit):
            _load_server_from_file("server.txt")

    def test_rejects_no_extension(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        no_ext = tmp_path / "server"
        no_ext.write_text("not python")

        with pytest.raises(SystemExit):
            _load_server_from_file("server")

    def test_rejects_pyc_extension(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pyc_file = tmp_path / "server.pyc"
        pyc_file.write_bytes(b"\x00")

        with pytest.raises(SystemExit):
            _load_server_from_file("server.pyc")

    def test_accepts_valid_py_in_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        server_file = tmp_path / "server.py"
        server_file.write_text(
            "from convilyn_sdk import ToolServer\n"
            'server = ToolServer(name="ok", description="ok")\n'
            '@server.tool(description="t")\n'
            "async def t(x: str) -> dict:\n"
            '    return {"x": x}\n'
        )

        result = _load_server_from_file("server.py")
        assert result.name == "ok"

    def test_accepts_subdirectory_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "src"
        sub.mkdir()
        server_file = sub / "app.py"
        server_file.write_text(
            "from convilyn_sdk import ToolServer\n"
            'server = ToolServer(name="sub", description="sub")\n'
            '@server.tool(description="t")\n'
            "async def t(x: str) -> dict:\n"
            '    return {"x": x}\n'
        )

        result = _load_server_from_file("src/app.py")
        assert result.name == "sub"


# ══════════════════════════════════════════════════════════════════════
# 2. server_runtime: Security Headers
# ══════════════════════════════════════════════════════════════════════


class TestSecurityHeaders:
    """All responses must include security headers."""

    @pytest.fixture
    def app(self):
        # allow_insecure=True: these tests exercise response headers on an
        # authorized server, not the auth gate itself.
        return _create_asgi_app(_make_server(), allow_insecure=True)

    def _get_header(self, headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
        for k, v in headers:
            if k == name:
                return v
        return None

    @pytest.mark.asyncio
    async def test_health_has_nosniff(self, app):
        _, _, headers = await _simulate_request(app, "GET", "/health")
        assert self._get_header(headers, b"x-content-type-options") == b"nosniff"

    @pytest.mark.asyncio
    async def test_health_has_frame_deny(self, app):
        _, _, headers = await _simulate_request(app, "GET", "/health")
        assert self._get_header(headers, b"x-frame-options") == b"DENY"

    @pytest.mark.asyncio
    async def test_health_has_no_store(self, app):
        _, _, headers = await _simulate_request(app, "GET", "/health")
        assert self._get_header(headers, b"cache-control") == b"no-store"

    @pytest.mark.asyncio
    async def test_404_has_security_headers(self, app):
        _, _, headers = await _simulate_request(app, "GET", "/unknown")
        assert self._get_header(headers, b"x-content-type-options") == b"nosniff"
        assert self._get_header(headers, b"x-frame-options") == b"DENY"
        assert self._get_header(headers, b"cache-control") == b"no-store"

    @pytest.mark.asyncio
    async def test_mcp_has_security_headers(self, app):
        rpc_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hi"}},
                "id": "1",
            }
        ).encode()
        _, _, headers = await _simulate_request(app, "POST", "/mcp", body=rpc_body)
        assert self._get_header(headers, b"x-content-type-options") == b"nosniff"


# ══════════════════════════════════════════════════════════════════════
# 3. server_runtime: Health Endpoint — No Tool Name Leakage
# ══════════════════════════════════════════════════════════════════════


class TestHealthEndpointInfoHiding:
    """Health endpoint must NOT reveal individual tool names."""

    @pytest.mark.asyncio
    async def test_health_returns_tool_count_not_names(self):
        app = _create_asgi_app(_make_server())

        status, data, _ = await _simulate_request(app, "GET", "/health")
        assert status == 200
        assert data["status"] == "healthy"
        assert data["tool_count"] == 2
        assert "tools" not in data

    @pytest.mark.asyncio
    async def test_health_includes_server_name_and_version(self):
        app = _create_asgi_app(_make_server())

        _, data, _ = await _simulate_request(app, "GET", "/health")
        assert data["server"] == "test-srv"
        assert data["version"] == "0.1.0"


# ══════════════════════════════════════════════════════════════════════
# 4. server_runtime: Manifest Endpoint
# ══════════════════════════════════════════════════════════════════════


class TestManifestEndpoint:
    """Manifest endpoint is now open (trust via VPC/IAM)."""

    @pytest.mark.asyncio
    async def test_manifest_accessible(self):
        app = _create_asgi_app(_make_server())
        status, data, _ = await _simulate_request(app, "GET", "/manifest")
        assert status == 200
        assert "server" in data
        assert "tools" in data


# ══════════════════════════════════════════════════════════════════════
# 5. server_runtime: Generic Error Messages (500)
# ══════════════════════════════════════════════════════════════════════


class TestGenericErrorMessages:
    """500 responses must not leak exception details."""

    @pytest.mark.asyncio
    async def test_500_does_not_leak_exception(self):
        app = _create_asgi_app(_make_server(), allow_insecure=True)
        body = json.dumps({"not": "jsonrpc"}).encode()
        status, data, _ = await _simulate_request(app, "POST", "/mcp", body=body)
        assert status == 500
        assert data["error"] == "Internal server error"
        assert "validation" not in data["error"].lower()
        assert "traceback" not in json.dumps(data).lower()


# ══════════════════════════════════════════════════════════════════════
# 6. MCP Endpoint — Tool Invocation
# ══════════════════════════════════════════════════════════════════════


class TestMCPEndpoint:
    """POST /mcp tool invocation."""

    @pytest.mark.asyncio
    async def test_mcp_tool_call(self):
        app = _create_asgi_app(_make_server(), allow_insecure=True)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hi"}},
                "id": "1",
            }
        ).encode()
        status, data, _ = await _simulate_request(app, "POST", "/mcp", body=body)
        assert status == 200
        assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_tool_data_auto_registered(self):
        """get_tool_data tool should be auto-registered in protocol layer."""
        app = _create_asgi_app(_make_server(), allow_insecure=True)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_tool_data", "arguments": {"ref_id": "td_nonexistent0"}},
                "id": "2",
            }
        ).encode()
        status, data, _ = await _simulate_request(app, "POST", "/mcp", body=body)
        assert status == 200
        # Should return not found but not crash
        assert data["result"]["success"] is False
        assert "NOT_FOUND" in str(data["result"]["error"])


# ══════════════════════════════════════════════════════════════════════
# 7. config: Default Host
# ══════════════════════════════════════════════════════════════════════


class TestConfigDefaults:
    """Config defaults must be secure."""

    def test_default_host_is_localhost(self):
        config = SDKConfig()
        assert config.server_host == "127.0.0.1"

    def test_from_env_defaults_to_localhost(self, monkeypatch):
        monkeypatch.delenv("CONVILYN_HOST", raising=False)
        config = SDKConfig.from_env()
        assert config.server_host == "127.0.0.1"

    def test_from_env_respects_override(self, monkeypatch):
        monkeypatch.setenv("CONVILYN_HOST", "0.0.0.0")
        config = SDKConfig.from_env()
        assert config.server_host == "0.0.0.0"

    def test_default_port(self):
        config = SDKConfig()
        assert config.server_port == 8080

    def test_is_local_default(self):
        config = SDKConfig()
        assert config.is_local is True

    def test_is_local_with_environment(self):
        config = SDKConfig(environment="production", server_host="0.0.0.0")
        assert config.is_local is False


# ══════════════════════════════════════════════════════════════════════
# 8. server.py: Argument Filtering in call_tool
# ══════════════════════════════════════════════════════════════════════


class TestArgumentFiltering:
    """call_tool must filter out undeclared arguments."""

    @pytest.mark.asyncio
    async def test_extra_args_are_filtered(self):
        server = _make_server()
        result = await server.call_tool(
            "echo",
            {
                "message": "hello",
                "admin": True,
                "__class__": "exploit",
            },
        )
        assert result == {"echo": "hello"}

    @pytest.mark.asyncio
    async def test_valid_args_pass_through(self):
        server = _make_server()
        result = await server.call_tool("echo", {"message": "test"})
        assert result == {"echo": "test"}

    @pytest.mark.asyncio
    async def test_missing_required_arg_raises(self):
        server = _make_server()
        with pytest.raises(TypeError):
            await server.call_tool("echo", {})


# ══════════════════════════════════════════════════════════════════════
# 9. scaffold: Project Name Validation
# ══════════════════════════════════════════════════════════════════════


class TestScaffoldNameValidation:
    """scaffold_project must reject unsafe project names."""

    def test_rejects_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("../evil", target_dir=tmp_path / "out")

    def test_rejects_slash(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("a/b", target_dir=tmp_path / "out")

    def test_rejects_space(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("my server", target_dir=tmp_path / "out")

    def test_rejects_semicolon(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("name;rm -rf /", target_dir=tmp_path / "out")

    def test_rejects_dot_only(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("..", target_dir=tmp_path / "out")

    def test_rejects_empty(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid project name"):
            scaffold_project("", target_dir=tmp_path / "out")

    def test_accepts_valid_name(self, tmp_path):
        out = scaffold_project("my-server_v2", target_dir=tmp_path / "my-server_v2")
        assert out.exists()

    def test_accepts_alphanumeric(self, tmp_path):
        out = scaffold_project("demo123", target_dir=tmp_path / "demo123")
        assert out.exists()


# ══════════════════════════════════════════════════════════════════════
# 10. server_runtime: _read_body — Chunked Body Assembly
# ══════════════════════════════════════════════════════════════════════


class TestReadBody:
    """Body reading must handle chunks correctly and enforce size limit."""

    @pytest.mark.asyncio
    async def test_single_chunk(self):
        async def receive():
            return {"body": b"hello", "more_body": False}

        result = await _read_body(receive)
        assert result == b"hello"

    @pytest.mark.asyncio
    async def test_multiple_chunks(self):
        chunks = [b"hello", b" ", b"world"]
        idx = 0

        async def receive():
            nonlocal idx
            chunk = chunks[idx]
            idx += 1
            return {"body": chunk, "more_body": idx < len(chunks)}

        result = await _read_body(receive)
        assert result == b"hello world"

    @pytest.mark.asyncio
    async def test_rejects_oversized_body(self):
        big_chunk = b"x" * (10 * 1024 * 1024 + 1)

        async def receive():
            return {"body": big_chunk, "more_body": False}

        with pytest.raises(ValueError, match="too large"):
            await _read_body(receive)


# ══════════════════════════════════════════════════════════════════════
# 11. server_runtime: Inbound /mcp authorization is FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════


def _hmac_headers(secret: str, body: bytes, *, ts: int = 1_000) -> list[tuple[bytes, bytes]]:
    """Build valid HMAC headers for an inbound /mcp request."""
    import hashlib
    import hmac

    message = f"{ts}".encode() + b"." + body
    sig = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return [
        (b"x-convilyn-signature", sig.encode()),
        (b"x-convilyn-timestamp", str(ts).encode()),
    ]


_MCP_BODY = json.dumps(
    {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"message": "hi"}},
        "id": "1",
    }
).encode()


class TestInboundAuthFailClosed:
    """Without a secret AND without an explicit opt-in, /mcp must reject."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)
        monkeypatch.delenv("CONVILYN_DEV_INSECURE", raising=False)
        monkeypatch.delenv("CONVILYN_ENVIRONMENT", raising=False)

    @pytest.mark.asyncio
    async def test_no_secret_no_optin_rejects_mcp(self):
        # Default app: allow_insecure defaults to False → fail closed.
        app = _create_asgi_app(_make_server(), SDKConfig(hmac_secret=None))
        status, data, _ = await _simulate_request(app, "POST", "/mcp", body=_MCP_BODY)
        assert status == 401
        assert data["code"] == "INVALID_SIGNATURE"

    @pytest.mark.asyncio
    async def test_no_secret_local_environment_still_rejects(self):
        # environment="local" must NOT bypass auth (the old fail-open path).
        cfg = SDKConfig(hmac_secret=None, environment="local")
        app = _create_asgi_app(_make_server(), cfg)
        status, _, _ = await _simulate_request(app, "POST", "/mcp", body=_MCP_BODY)
        assert status == 401

    @pytest.mark.asyncio
    async def test_explicit_insecure_allows_mcp(self):
        app = _create_asgi_app(_make_server(), SDKConfig(hmac_secret=None), allow_insecure=True)
        status, data, _ = await _simulate_request(app, "POST", "/mcp", body=_MCP_BODY)
        assert status == 200
        assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_valid_signature_passes(self):
        import time

        secret = "shh-secret"  # pragma: allowlist secret
        cfg = SDKConfig(hmac_secret=secret)
        app = _create_asgi_app(_make_server(), cfg)
        # Use a fresh timestamp so it falls inside the 300s replay window.
        headers = _hmac_headers(secret, _MCP_BODY, ts=int(time.time()))
        status, data, _ = await _simulate_request(
            app, "POST", "/mcp", body=_MCP_BODY, headers=headers
        )
        assert status == 200
        assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_bad_signature_rejected_even_with_secret(self):
        cfg = SDKConfig(hmac_secret="shh-secret")  # pragma: allowlist secret
        app = _create_asgi_app(_make_server(), cfg)
        headers = [
            (b"x-convilyn-signature", b"deadbeef"),
            (b"x-convilyn-timestamp", b"1000"),
        ]
        status, _, _ = await _simulate_request(app, "POST", "/mcp", body=_MCP_BODY, headers=headers)
        assert status == 401


class TestStartServerFailClosed:
    """start_server refuses to boot without a secret unless opted in."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)
        monkeypatch.delenv("CONVILYN_DEV_INSECURE", raising=False)
        monkeypatch.delenv("CONVILYN_ENVIRONMENT", raising=False)

    def test_raises_without_secret_or_optin(self, monkeypatch):
        from convilyn_sdk._internal import server_runtime

        called = {"ran": False}
        monkeypatch.setattr(
            server_runtime.uvicorn, "run", lambda *a, **k: called.__setitem__("ran", True)
        )
        with pytest.raises(server_runtime.ConvilynStartupError, match="CONVILYN_HMAC_SECRET"):
            server_runtime.start_server(_make_server())
        assert called["ran"] is False

    def test_env_optin_allows_boot(self, monkeypatch):
        from convilyn_sdk._internal import server_runtime

        monkeypatch.setenv("CONVILYN_DEV_INSECURE", "1")
        ran = {"ok": False}
        monkeypatch.setattr(
            server_runtime.uvicorn, "run", lambda *a, **k: ran.__setitem__("ok", True)
        )
        server_runtime.start_server(_make_server())
        assert ran["ok"] is True

    def test_dev_flag_allows_boot(self, monkeypatch):
        from convilyn_sdk._internal import server_runtime

        ran = {"ok": False}
        monkeypatch.setattr(
            server_runtime.uvicorn, "run", lambda *a, **k: ran.__setitem__("ok", True)
        )
        server_runtime.start_server(_make_server(), allow_insecure=True)
        assert ran["ok"] is True

    def test_secret_allows_boot(self, monkeypatch):
        from convilyn_sdk._internal import server_runtime

        monkeypatch.setenv("CONVILYN_HMAC_SECRET", "shh")  # pragma: allowlist secret
        ran = {"ok": False}
        monkeypatch.setattr(
            server_runtime.uvicorn, "run", lambda *a, **k: ran.__setitem__("ok", True)
        )
        server_runtime.start_server(_make_server())
        assert ran["ok"] is True

    @pytest.mark.parametrize(
        "val,expected",
        [
            ("1", True),
            ("true", True),
            ("YES", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("", False),
            ("maybe", False),
        ],
    )
    def test_dev_insecure_env_parsing(self, monkeypatch, val, expected):
        from convilyn_sdk._internal.server_runtime import _dev_insecure_requested

        monkeypatch.setenv("CONVILYN_DEV_INSECURE", val)
        assert _dev_insecure_requested() is expected
