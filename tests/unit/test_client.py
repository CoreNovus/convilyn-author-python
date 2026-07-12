"""Tests for ConvilynClient — mock HTTP, auth, push flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from convilyn_sdk import ToolServer, WorkflowSpec
from convilyn_sdk.client import ConvilynClient, ConvilynClientError


def _make_server():
    server = ToolServer(name="srv", description="T", version="0.1.0")

    @server.tool(description="T")
    async def t1(text: str = "x") -> dict:
        return {"ok": True}

    return server


def _make_workflow():
    return (
        WorkflowSpec("test_wf", name="Test", version="1.0.0")
        .use_tools("srv:t1")
        .use_servers("srv")
        .add_phase("P", "D")
    )


# ── Construction ────────────────────────────────────────────────


class TestClientConstruction:
    def test_default_config(self):
        client = ConvilynClient(api_key="cvl_test_key")  # pragma: allowlist secret
        assert client._api_key == "cvl_test_key"  # pragma: allowlist secret
        # Default base derives from platform_url AND includes /api/v1, so the
        # relative /developers/* paths resolve against the mount (issue #2011).
        assert client._base_url == "https://api.convilyn.corenovus.com/api/v1"

    def test_default_base_composes_the_full_developer_path(self):
        # The literal URL a default-config call would hit — must include /api/v1.
        client = ConvilynClient(api_key="cvl_test")
        assert (
            f"{client._base_url}/developers/register"
            == "https://api.convilyn.corenovus.com/api/v1/developers/register"
        )

    def test_api_v1_is_not_doubled_when_platform_url_already_has_it(self):
        env = {"CONVILYN_PLATFORM_URL": "https://api.convilyn.corenovus.com/api/v1"}
        with patch.dict("os.environ", env):
            client = ConvilynClient(api_key="cvl_test")
            assert client._base_url == "https://api.convilyn.corenovus.com/api/v1"

    def test_custom_url_is_used_verbatim(self):
        # An explicit base_url is the caller's responsibility — no /api/v1 added.
        client = ConvilynClient(api_key="cvl_test", base_url="https://custom.api.com/")
        assert client._base_url == "https://custom.api.com"

    def test_env_config(self):
        env = {"CONVILYN_API_KEY": "cvl_env_key"}  # pragma: allowlist secret
        with patch.dict("os.environ", env):
            from convilyn_sdk.config import SDKConfig

            config = SDKConfig.from_env()
            assert config.api_key == "cvl_env_key"  # pragma: allowlist secret

    def test_no_api_key_raises_on_auth(self):
        client = ConvilynClient(api_key=None, base_url="http://test")
        with pytest.raises(ConvilynClientError, match="API key not set"):
            client._auth_headers()

    def test_consumer_key_rejected_at_construction(self):
        # A consumer ck_ key pasted into the Author SDK is caught up front with a
        # precise error, not an opaque 401 from the developer portal later.
        with pytest.raises(ConvilynClientError, match="consumer API key"):
            ConvilynClient(api_key="ck_consumer_data_plane_key")  # pragma: allowlist secret

    def test_consumer_key_not_leaked_in_error(self):
        with pytest.raises(ConvilynClientError) as excinfo:
            ConvilynClient(api_key="ck_super_secret_consumer_token")  # pragma: allowlist secret
        assert "super_secret_consumer_token" not in str(excinfo.value)


# ── Auth Headers ────────────────────────────────────────────────


class TestAuthHeaders:
    def test_auth_header_format(self):
        client = ConvilynClient(api_key="cvl_test_123")
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer cvl_test_123"


# ── ConvilynClientError ─────────────────────────────────────────


class TestClientError:
    def test_error_attributes(self):
        err = ConvilynClientError(422, "Validation failed")
        assert err.status_code == 422
        assert err.detail == "Validation failed"
        assert "HTTP 422" in str(err)


# ── HTTP Requests (mocked) ──────────────────────────────────────


class TestHTTPRequests:
    @pytest.mark.asyncio
    async def test_request_success(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.request.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client._request("GET", "/test")
            assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_request_error_with_json_detail(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")

        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"detail": "Bad input"}
        mock_response.text = "Bad input"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.request.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            with pytest.raises(ConvilynClientError) as exc_info:
                await client._request("POST", "/test", json={"x": 1})
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_request_error_non_json(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = Exception("not json")
        mock_response.text = "Internal error"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.request.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            with pytest.raises(ConvilynClientError) as exc_info:
                await client._request("GET", "/fail")
            assert "Internal error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_request_204_returns_empty(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.request.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client._request("DELETE", "/resource")
            assert result == {}

    @pytest.mark.asyncio
    async def test_request_no_auth(self):
        client = ConvilynClient(api_key=None, base_url="http://test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.request.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client._request("POST", "/register", auth=False)
            assert result == {"ok": True}


# ── API Methods (mocked _request) ───────────────────────────────


class TestAPIMethods:
    @pytest.mark.asyncio
    async def test_register(self):
        client = ConvilynClient(api_key=None, base_url="http://test")
        client._request = AsyncMock(
            return_value={
                "developer_id": "dev_123",
                "api_key": "cvl_new_key",  # pragma: allowlist secret
                "status": "active",
            }
        )

        result = await client.register("a@b.com", "Dev")
        assert result["developer_id"] == "dev_123"
        assert client._api_key == "cvl_new_key"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_register_with_company(self):
        client = ConvilynClient(api_key=None, base_url="http://test")
        client._request = AsyncMock(return_value={"developer_id": "d1", "api_key": "cvl_k"})

        await client.register("a@b.com", "Dev", company="Corp")
        call_args = client._request.call_args
        assert call_args[1]["json"]["company"] == "Corp"

    @pytest.mark.asyncio
    async def test_register_no_overwrite_existing_key(self):
        client = ConvilynClient(api_key="cvl_existing", base_url="http://test")
        client._request = AsyncMock(return_value={"developer_id": "d1", "api_key": "cvl_new"})

        await client.register("a@b.com", "Dev")
        # not overwritten
        assert client._api_key == "cvl_existing"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_submit_server(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"server_id": "srv_1"})

        result = await client.submit_server({"server": {"name": "s"}}, "https://s.com")
        assert result["server_id"] == "srv_1"

    @pytest.mark.asyncio
    async def test_list_servers_returns_list(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value=[{"server_id": "s1"}])
        result = await client.list_servers()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_servers_wraps_non_list(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"server_id": "s1"})
        result = await client.list_servers()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_server_status(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "verified"})
        result = await client.get_server_status("srv_1")
        assert result["status"] == "verified"

    @pytest.mark.asyncio
    async def test_test_server(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "passed"})
        result = await client.test_server("srv_1")
        assert result["status"] == "passed"

    @pytest.mark.asyncio
    async def test_test_server_with_slots(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "passed"})
        await client.test_server("srv_1", slots={"lang": "en"})
        call_args = client._request.call_args
        assert call_args[1]["json"]["slots"]["lang"] == "en"

    @pytest.mark.asyncio
    async def test_deactivate_server(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "suspended"})
        result = await client.deactivate_server("srv_1")
        assert result["status"] == "suspended"

    @pytest.mark.asyncio
    async def test_submit_workflow(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"workflow_id": "wf_1"})
        result = await client.submit_workflow({"spec_id": "x"}, ["srv_1"])
        assert result["workflow_id"] == "wf_1"

    @pytest.mark.asyncio
    async def test_submit_workflow_serverless_default(self):
        """C3: server_ids may be omitted — a spec built on platform tools
        needs no self-hosted server; the wire body carries an empty list."""
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"workflow_id": "wf_1"})
        await client.submit_workflow({"spec_id": "x"})
        body = client._request.call_args.kwargs["json"]
        assert body["server_ids"] == []

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value=[{"workflow_id": "wf_1"}])
        result = await client.list_workflows()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_workflows_wraps_non_list(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"workflow_id": "wf_1"})
        result = await client.list_workflows()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_workflow_status(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "active"})
        result = await client.get_workflow_status("wf_1")
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_test_workflow(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"all_passed": True})
        result = await client.test_workflow("wf_1")
        assert result["all_passed"] is True

    @pytest.mark.asyncio
    async def test_test_workflow_with_input(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"all_passed": True})
        await client.test_workflow("wf_1", test_input={"files": ["f.pdf"]})
        call_args = client._request.call_args
        assert call_args[1]["json"]["test_input"]["files"] == ["f.pdf"]

    @pytest.mark.asyncio
    async def test_deactivate_workflow(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client._request = AsyncMock(return_value={"status": "suspended"})
        result = await client.deactivate_workflow("wf_1")
        assert result["status"] == "suspended"


# ── Push Orchestration ──────────────────────────────────────────


class TestPush:
    @pytest.mark.asyncio
    async def test_push_success(self):
        client = ConvilynClient(api_key="cvl_test", base_url="http://test")
        client.submit_server = AsyncMock(
            return_value={
                "server_id": "srv_1",
                "server_name": "srv",
                "status": "submitted",
            }
        )
        client.submit_workflow = AsyncMock(
            return_value={
                "workflow_id": "wf_1",
                "spec_id": "test_wf",
                "status": "submitted",
            }
        )

        server = _make_server()
        workflow = _make_workflow()

        result = await client.push(server, workflow, "https://my.server.com")

        assert result["server_id"] == "srv_1"
        assert result["workflow_id"] == "wf_1"
        assert result["server_status"] == "submitted"
        assert result["workflow_status"] == "submitted"

        # Verify submit_server called with manifest
        manifest_arg = client.submit_server.call_args[0][0]
        assert manifest_arg["server"]["name"] == "srv"

        # Verify submit_workflow called with compiled spec
        spec_arg = client.submit_workflow.call_args[0][0]
        assert spec_arg["spec_id"] == "test_wf"
