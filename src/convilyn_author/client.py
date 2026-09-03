"""ConvilynClient — authenticated client for the Convilyn developer platform.

Wraps the Developer Portal REST API for submitting tool servers and
managing developer resources. Workflow authoring lives in the Convilyn
chat Builder — this client operates the tool-server surface only.

Usage::

    from convilyn_author import ConvilynClient

    client = ConvilynClient(api_key="cvl_...")

    # Register (no auth needed)
    result = await client.register(email="dev@example.com", name="Dev")

    # Push a tool server
    push_result = await client.push(
        server=server,
        endpoint_url="https://my-server.example.com",
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from convilyn_author.config import SDKConfig

if TYPE_CHECKING:
    from convilyn_author.server import ToolServer


def _with_api_v1(platform_url: str) -> str:
    """Return ``platform_url`` with a trailing ``/api/v1`` (idempotent).

    The Developer Portal routes are mounted under ``/api/v1``; this composes the
    default base so relative ``/developers/*`` paths resolve correctly.
    """
    trimmed = platform_url.rstrip("/")
    return trimmed if trimmed.endswith("/api/v1") else f"{trimmed}/api/v1"


#: The developer-portal author key prefix this SDK authenticates with.
AUTHOR_KEY_PREFIXES: tuple[str, ...] = ("cvl_", "cvi_")  # pragma: allowlist secret

#: The consumer data-plane key prefix — NOT an author key. The author SDK
#: rejects it up front with a precise error instead of a later opaque 401.
CONSUMER_KEY_PREFIX = "ck_"  # pragma: allowlist secret


def _is_consumer_key(key: str) -> bool:
    """True when ``key`` is a consumer data-plane key, not an author/portal token."""
    return key.startswith(CONSUMER_KEY_PREFIX)


def _mask_key(key: str) -> str:
    """Mask a secret for safe display: ``cvl_a…9f`` (or ``***`` when too short)."""
    return f"{key[:4]}…{key[-2:]}" if len(key) > 8 else "***"


class ConvilynClientError(Exception):
    """Raised when a platform API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class ConvilynClient:
    """Authenticated client for the Convilyn developer platform.

    Reads ``CONVILYN_API_KEY`` and ``CONVILYN_PLATFORM_URL`` from the
    environment if not provided explicitly.

    Every public method on this client is an async coroutine and MUST be
    awaited (run under ``asyncio.run(...)`` from sync code). Calling one
    without ``await`` returns an un-awaited coroutine object — the request
    is silently never sent.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        config = SDKConfig.from_env()
        self._api_key = api_key or config.api_key
        # Reject a consumer data-plane key pasted in by mistake with a precise
        # error, instead of the developer portal answering with an opaque 401.
        # The author SDK authenticates with a cvl_/cvi_ developer key; any other
        # prefix is accepted (forward-compat). Mirrors the consumer SDKs' inverse
        # guard. An empty key is allowed here — register() mints one.
        if self._api_key and _is_consumer_key(self._api_key):
            raise ConvilynClientError(
                0,
                f"{_mask_key(self._api_key)} looks like a Convilyn consumer API key "
                f'("{CONSUMER_KEY_PREFIX}"), not an Author SDK / developer-portal token. '
                "The Author SDK authenticates with a cvl_ developer key — register() to "
                "mint one, or set CONVILYN_API_KEY to your cvl_ key. (Consumer keys call "
                "the data-plane API; they do not register tool servers.)",
            )
        # The Developer Portal is mounted under /api/v1 (e.g.
        # /api/v1/developers/register). The paths in this client are relative to
        # that mount, so the default base derived from ``platform_url`` must
        # include /api/v1 or every call 404s. An explicitly
        # supplied ``base_url`` is used verbatim — the caller is responsible for
        # including any prefix.
        if base_url is not None:
            self._base_url = base_url.rstrip("/")
        else:
            self._base_url = _with_api_v1(config.platform_url)
        self._timeout = timeout

    # ── Internal helpers ──────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization header from API key."""
        if not self._api_key:
            raise ConvilynClientError(
                0, "API key not set. Provide api_key or set CONVILYN_API_KEY."
            )
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        """Make an HTTP request to the platform API."""
        headers = self._auth_headers() if auth else {}
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(method, url, json=json, headers=headers)

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ConvilynClientError(response.status_code, detail)

        if response.status_code == 204:
            return {}
        return response.json()

    # ── Developer Registration ────────────────────────────────────

    async def register(
        self,
        email: str,
        name: str,
        company: str | None = None,
    ) -> dict[str, Any]:
        """Register a new developer account (no auth needed).

        This is an async coroutine and must be awaited. A bare
        ``ConvilynClient().register(...)`` call from sync code returns an
        un-awaited coroutine and never performs the request::

            result = await ConvilynClient().register(
                email="you@example.com", name="Your Name"
            )
            # from sync code: asyncio.run(ConvilynClient().register(...))

        Returns:
            Dict with developer_id, api_key, and status.
            Save the api_key — it is only shown once.
        """
        payload: dict[str, Any] = {"email": email, "name": name}
        if company:
            payload["company"] = company

        result = await self._request("POST", "/developers/register", json=payload, auth=False)

        # Auto-set API key for subsequent calls
        if "api_key" in result and not self._api_key:
            self._api_key = result["api_key"]

        return result

    # ── Server Operations ─────────────────────────────────────────

    async def submit_server(
        self,
        manifest: dict[str, Any],
        endpoint_url: str,
    ) -> dict[str, Any]:
        """Submit an MCP server manifest for verification.

        Args:
            manifest: ConvilynManifest dict (from server.synth().to_dict()).
            endpoint_url: HTTPS URL where the server is deployed.

        Returns:
            Dict with server_id, server_name, and status.
        """
        return await self._request(
            "POST",
            "/developers/servers",
            json={"manifest": manifest, "endpoint_url": endpoint_url},
        )

    async def list_servers(self) -> list[dict[str, Any]]:
        """List all servers for the authenticated developer."""
        result = await self._request("GET", "/developers/servers")
        return result if isinstance(result, list) else [result]

    async def list_platform_tools(self) -> dict[str, Any]:
        """List the platform's built-in MCP tools (vision / OCR / LLM / …).

        Returns the platform tool catalog so you can discover the built-in
        tools your own tools will coexist with. The response is
        ``{"items": [...], "servers": [...]}``; each item carries ``toolName``,
        ``mcpServer``, ``displayName``, ``category``, ``description``,
        ``costMicroU`` and ``riskLevel``.

        This is an async coroutine and must be awaited. Requires a ``cvl_``
        developer key (the one ``register()`` mints).
        """
        return await self._request("GET", "/developers/tools/catalog")

    async def get_server_status(self, server_id: str) -> dict[str, Any]:
        """Check verification status of a submitted server."""
        return await self._request("GET", f"/developers/servers/{server_id}/status")

    async def test_server(
        self,
        server_id: str,
        slots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a sandbox test for a server."""
        return await self._request(
            "POST",
            f"/developers/servers/{server_id}/test",
            json={"slots": slots or {}},
        )

    async def deactivate_server(self, server_id: str) -> dict[str, Any]:
        """Deactivate a server."""
        return await self._request("DELETE", f"/developers/servers/{server_id}")

    # ── Convilyn-Hosted Author Runtime ───────────────────────────

    async def deploy_hosted_runtime(
        self,
        manifest: dict[str, Any],
        *,
        region: str,
    ) -> dict[str, Any]:
        """Deploy a tool server into the Convilyn-Hosted Author Runtime.

        Counterpart to :meth:`submit_server` — instead of registering an
        existing caller-deployed endpoint, this hands the manifest to the
        platform, which provisions a sandboxed hosted runtime in the
        Convilyn-managed environment and returns the public endpoint URL
        that fronts it.

        Args:
            manifest: ``ConvilynManifest`` dict (from ``server.synth().to_dict()``).
            region: AWS region to deploy into (e.g. ``"us-east-1"``).

        Returns:
            Dict with ``runtime_id``, ``endpoint_url``, ``region``,
            and ``status``.

        Raises:
            ConvilynClientError: backend failure. Backend code
                ``HOSTED_NOT_AVAILABLE`` surfaces as a plain
                ``ConvilynClientError`` with status **503** (older
                platform builds answered 501; environments where the
                author-runtime router is unmounted answer 404) — callers
                can catch it and fall back to ``submit_server`` + BYO
                ``--endpoint-url`` if their CI needs a hard guarantee.
        """
        payload: dict[str, Any] = {
            "manifest": manifest,
            "region": region,
        }
        return await self._request("POST", "/developers/runtimes/hosted", json=payload)

    async def rollback_hosted_runtime(self, runtime_id: str) -> dict[str, Any]:
        """Roll a hosted runtime back to its previous active version.

        The Lambda alias atomically flips to the prior version; the
        previous container image stays in ECR (see lifecycle policy on
        the stack) so subsequent rollbacks can continue stepping back.

        Returns:
            Dict with ``runtime_id``, ``version`` (now-active version),
            and ``status``.
        """
        return await self._request("POST", f"/developers/runtimes/{runtime_id}/rollback")

    async def get_hosted_runtime_logs(
        self,
        runtime_id: str,
        *,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent log lines for a hosted runtime.

        Server-side filtering by ``since`` keeps the response payload
        bounded; the SDK trusts the server's interpretation rather
        than parsing timestamps locally.

        Args:
            runtime_id: The runtime identifier returned by ``deploy_hosted_runtime``.
            since: ISO-8601 timestamp or relative shorthand (e.g.
                ``"5m"``, ``"1h"``) — the platform decides the
                parsing rules.
            limit: Maximum entries to return (server caps at ~1000).

        Returns:
            List of log entry dicts in chronological order; each entry
            carries ``timestamp``, ``message``, and ``level`` keys.
        """
        path = f"/developers/runtimes/{runtime_id}/logs?limit={int(limit)}"
        if since:
            path = f"{path}&since={since}"
        result = await self._request("GET", path)
        # The backend may return either a bare list (newer) or a
        # ``{"entries": [...]}`` envelope; accept both so the SDK
        # doesn't break when the wire shape stabilises.
        if isinstance(result, list):
            return result
        return result.get("entries", []) if isinstance(result, dict) else []

    # ── Orchestrated Push ─────────────────────────────────────────

    async def push(
        self,
        server: ToolServer,
        endpoint_url: str,
    ) -> dict[str, Any]:
        """Push a tool server to the platform in one operation.

        Orchestrates: synth manifest → submit server.

        Args:
            server: ToolServer instance with registered tools.
            endpoint_url: HTTPS URL where the tool server is deployed.

        Returns:
            Dict with server_id, server_name, and status.
        """
        # 1. Compile manifest
        manifest = server.synth()
        manifest_dict = manifest.to_dict()

        # 2. Submit server
        server_result = await self.submit_server(manifest_dict, endpoint_url)
        server_id = server_result["server_id"]

        return {
            "server_id": server_id,
            "server_name": server_result.get("server_name", server.name),
            "server_status": server_result.get("status", "submitted"),
        }
