"""ConvilynClient hosted-runtime methods — 4-category coverage.

R6 / #720 surfaces:
* :meth:`ConvilynClient.deploy_hosted_runtime`
* :meth:`ConvilynClient.rollback_hosted_runtime`
* :meth:`ConvilynClient.get_hosted_runtime_logs`

These wrap the platform's ``/developers/runtimes/hosted`` API; the
follow-up backend PR provides the real handler. Tests pin the wire
shape so the SDK and the backend stay aligned through the staged
rollout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from convilyn_author.client import ConvilynClient, ConvilynClientError

# ── 1. Logic — happy-path wire shape ────────────────────────────


class TestDeployHostedLogic:
    @pytest.mark.asyncio
    async def test_deploy_sends_manifest_and_region(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(
            return_value={
                "runtime_id": "art_abc",
                "endpoint_url": "https://router.convilyn.com/r/art_abc",
                "region": "us-east-1",
                "status": "provisioning",
            }
        )
        result = await client.deploy_hosted_runtime(
            {"server": {"name": "demo"}, "tools": []}, region="us-east-1"
        )

        assert result["runtime_id"] == "art_abc"
        client._request.assert_awaited_once()
        method, path = client._request.await_args.args
        assert method == "POST"
        assert path == "/developers/runtimes/hosted"
        body = client._request.await_args.kwargs["json"]
        assert body["region"] == "us-east-1"
        assert body["manifest"] == {"server": {"name": "demo"}, "tools": []}


class TestRollbackLogic:
    @pytest.mark.asyncio
    async def test_rollback_hits_runtime_path(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(
            return_value={"runtime_id": "art_abc", "version": 2, "status": "active"}
        )
        await client.rollback_hosted_runtime("art_abc")

        method, path = client._request.await_args.args
        assert method == "POST"
        assert path == "/developers/runtimes/art_abc/rollback"


class TestLogsLogic:
    @pytest.mark.asyncio
    async def test_logs_returns_list_when_server_emits_bare_list(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        rows = [
            {"timestamp": "2026-05-26T10:00:00Z", "level": "INFO", "message": "boot"},
            {"timestamp": "2026-05-26T10:00:01Z", "level": "INFO", "message": "ok"},
        ]
        client._request = AsyncMock(return_value=rows)
        result = await client.get_hosted_runtime_logs("art_abc")
        assert result == rows

    @pytest.mark.asyncio
    async def test_logs_unwraps_entries_envelope(self) -> None:
        """Forward-compat: backend may switch to ``{"entries": [...]}``."""
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        rows = [{"timestamp": "t", "level": "INFO", "message": "m"}]
        client._request = AsyncMock(return_value={"entries": rows})

        result = await client.get_hosted_runtime_logs("art_abc")
        assert result == rows


# ── 2. Boundary — since / limit query encoding ─────────────────


class TestLogsBoundary:
    @pytest.mark.asyncio
    async def test_default_limit_encoded(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(return_value=[])
        await client.get_hosted_runtime_logs("art_abc")

        method, path = client._request.await_args.args
        assert method == "GET"
        assert path == "/developers/runtimes/art_abc/logs?limit=100"

    @pytest.mark.asyncio
    async def test_since_appended_when_provided(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(return_value=[])
        await client.get_hosted_runtime_logs("art_abc", since="5m", limit=50)

        _, path = client._request.await_args.args
        assert path == "/developers/runtimes/art_abc/logs?limit=50&since=5m"

    @pytest.mark.asyncio
    async def test_unexpected_envelope_yields_empty_list(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        # e.g. backend returns a bare dict without ``entries`` key.
        client._request = AsyncMock(return_value={"meta": "info"})
        result = await client.get_hosted_runtime_logs("art_abc")
        assert result == []


# ── 3. Error — 501 NOT_IMPLEMENTED surfaces clearly ────────────


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_501_passes_through_as_client_error(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(
            side_effect=ConvilynClientError(
                501,
                "Convilyn-Hosted Author Runtime is not yet provisioned",
            )
        )
        with pytest.raises(ConvilynClientError) as exc_info:
            await client.deploy_hosted_runtime({"x": 1}, region="us-east-1")
        assert exc_info.value.status_code == 501

    @pytest.mark.asyncio
    async def test_rollback_propagates_404(self) -> None:
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(side_effect=ConvilynClientError(404, "runtime not found"))
        with pytest.raises(ConvilynClientError) as exc_info:
            await client.rollback_hosted_runtime("art_missing")
        assert exc_info.value.status_code == 404


# ── 4. Object-state — auth headers still injected through _request ──


class TestObjectState:
    @pytest.mark.asyncio
    async def test_deploy_invokes_underlying_request(self) -> None:
        """Sanity: the new method routes through ``_request``, so auth
        + base-url handling are inherited automatically."""
        client = ConvilynClient(api_key="cvl_t", base_url="http://test")
        client._request = AsyncMock(return_value={"runtime_id": "x"})

        await client.deploy_hosted_runtime({"k": "v"}, region="ap-northeast-1")

        assert client._request.await_count == 1
