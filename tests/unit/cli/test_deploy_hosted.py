"""CLI tests for the R6 hosted-runtime subcommands.

Covers ``convilyn-author deploy``, ``rollback``, and ``logs``. The
runner uses ``CliRunner`` like the rest of the CLI suite; backend
calls are mocked at the ``ConvilynClient`` boundary so the tests do
not require a live platform.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from convilyn_author.cli.main import cli
from convilyn_author.client import ConvilynClientError


def _write_server(path) -> None:
    path.write_text(
        "from convilyn_author import ToolServer\n"
        'server = ToolServer(name="demo", description="d", version="0.1.0")\n'
        '@server.tool(description="ping")\n'
        "async def ping() -> dict:\n"
        '    return {"ok": True}\n'
    )


# ── 1. Logic — deploy success path ───────────────────────────────


class TestDeployLogic:
    def test_deploy_hosted_with_server_only(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path / "server.py")

        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.deploy_hosted_runtime = AsyncMock(
                return_value={
                    "runtime_id": "art_abc",
                    "endpoint_url": "https://router.convilyn.com/r/art_abc",
                    "status": "provisioning",
                }
            )
            result = runner.invoke(
                cli,
                ["deploy", "--hosted", "--region", "us-east-1"],
            )

        assert result.exit_code == 0, result.output
        assert "art_abc" in result.output
        assert "router.convilyn.com" in result.output
        instance.deploy_hosted_runtime.assert_awaited_once()
        call_kwargs = instance.deploy_hosted_runtime.await_args.kwargs
        assert call_kwargs["region"] == "us-east-1"


# ── 2. Boundary — BYO redirect, default region ──────────────────


class TestDeployBoundary:
    def test_deploy_without_hosted_redirects_to_push(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path / "server.py")

        runner = CliRunner()
        result = runner.invoke(cli, ["deploy"])

        assert result.exit_code != 0
        assert "--hosted" in result.output
        assert "push" in result.output

    def test_default_region_is_us_east_1(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path / "server.py")

        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.deploy_hosted_runtime = AsyncMock(
                return_value={"runtime_id": "x", "endpoint_url": "y", "status": "z"}
            )
            runner.invoke(cli, ["deploy", "--hosted"])

        call_kwargs = instance.deploy_hosted_runtime.await_args.kwargs
        assert call_kwargs["region"] == "us-east-1"


# ── 3. Error — 501 surfaces with BYO fallback hint ──────────────


class TestDeployError:
    def test_501_surfaces_byo_fallback_message(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path / "server.py")

        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.deploy_hosted_runtime = AsyncMock(
                side_effect=ConvilynClientError(
                    501, "Convilyn-Hosted Author Runtime is not yet provisioned"
                )
            )
            result = runner.invoke(cli, ["deploy", "--hosted"])

        assert result.exit_code == 1
        assert "BYO" in result.output or "push --endpoint-url" in result.output

    def test_500_surfaces_generic_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path / "server.py")

        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.deploy_hosted_runtime = AsyncMock(side_effect=ConvilynClientError(500, "boom"))
            result = runner.invoke(cli, ["deploy", "--hosted"])

        assert result.exit_code == 1
        assert "boom" in result.output


# ── 4. Object-state — rollback + logs CLI plumbing ──────────────


class TestRollbackCli:
    def test_rollback_success(self) -> None:
        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.rollback_hosted_runtime = AsyncMock(
                return_value={"runtime_id": "art_abc", "version": 3, "status": "active"}
            )
            result = runner.invoke(cli, ["rollback", "art_abc"])
        assert result.exit_code == 0, result.output
        assert "3" in result.output
        instance.rollback_hosted_runtime.assert_awaited_once_with("art_abc")

    def test_rollback_propagates_error(self) -> None:
        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.rollback_hosted_runtime = AsyncMock(
                side_effect=ConvilynClientError(404, "no such runtime")
            )
            result = runner.invoke(cli, ["rollback", "art_missing"])
        assert result.exit_code == 1
        assert "no such runtime" in result.output


class TestLogsCli:
    def test_logs_prints_entries(self) -> None:
        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.get_hosted_runtime_logs = AsyncMock(
                return_value=[
                    {"timestamp": "2026-05-26T10:00:00Z", "level": "INFO", "message": "boot"},
                    {"timestamp": "2026-05-26T10:00:01Z", "level": "ERROR", "message": "x"},
                ]
            )
            result = runner.invoke(cli, ["logs", "art_abc", "--since", "5m"])

        assert result.exit_code == 0, result.output
        assert "boot" in result.output
        assert "ERROR" in result.output
        call_kwargs = instance.get_hosted_runtime_logs.await_args.kwargs
        assert call_kwargs["since"] == "5m"
        assert call_kwargs["limit"] == 100

    def test_logs_empty_response(self) -> None:
        runner = CliRunner()
        with patch("convilyn_author.client.ConvilynClient") as MockClient:
            instance = MockClient.return_value
            instance.get_hosted_runtime_logs = AsyncMock(return_value=[])
            result = runner.invoke(cli, ["logs", "art_abc"])
        assert result.exit_code == 0
        assert "No log entries" in result.output
