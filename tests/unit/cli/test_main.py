"""Tests for the CLI commands."""

import json

import pytest
from click.testing import CliRunner

from convilyn_author.cli.main import (
    _load_server_from_file,
    _load_workflow_from_file,
    cli,
)
from convilyn_author.cli.scaffold import scaffold_project

# ── Helpers ────────────────────────────────────────────────────────


_SERVER_SOURCE_OK = (
    "from convilyn_author import ToolServer\n"
    'server = ToolServer(name="t", description="t", version="0.1.0")\n'
    '@server.tool(description="ping")\n'
    "async def ping() -> dict:\n"
    '    return {"pong": True}\n'
)


_WORKFLOW_SOURCE_OK = (
    "from convilyn_author import WorkflowSpec\n"
    "workflow = (\n"
    '    WorkflowSpec("demo", name="Demo")\n'
    '    .with_input(types=["document"], formats=["pdf"])\n'
    '    .with_output(format="json", additional={"type": "demo_result"})\n'
    '    .add_phase("Phase1", "Step")\n'
    ")\n"
)


def _write_server(tmp_path, body: str = _SERVER_SOURCE_OK) -> None:
    (tmp_path / "server.py").write_text(body, encoding="utf-8")


def _write_workflow(tmp_path, body: str = _WORKFLOW_SOURCE_OK) -> None:
    (tmp_path / "workflow.py").write_text(body, encoding="utf-8")


class TestScaffold:
    def test_creates_project_structure(self, tmp_path):
        out = scaffold_project("my-server", target_dir=tmp_path / "my-server")
        assert (out / "server.py").exists()
        assert (out / "pyproject.toml").exists()
        assert (out / "tests" / "test_my_server.py").exists()
        assert (out / ".gitignore").exists()
        assert (out / ".env.example").exists()
        assert (out / "Dockerfile").exists()

    def test_server_py_content(self, tmp_path):
        out = scaffold_project("demo", target_dir=tmp_path / "demo")
        content = (out / "server.py").read_text(encoding="utf-8")
        assert 'name="demo"' in content
        assert "ToolServer" in content
        assert "data_store.store" in content

    def test_pyproject_content(self, tmp_path):
        out = scaffold_project("demo", target_dir=tmp_path / "demo")
        content = (out / "pyproject.toml").read_text()
        assert 'name = "demo"' in content
        assert "convilyn-author" in content


class TestCLIInit:
    def test_init_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "test-project"])
        assert result.exit_code == 0
        assert "Project created" in result.output
        # Next-step hint must use the real binary, not the removed `convilyn` alias.
        assert "convilyn-author dev" in result.output
        assert (tmp_path / "test-project" / "server.py").exists()


class TestCLISynth:
    def test_synth_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        server_file = tmp_path / "server.py"
        server_file.write_text(
            "from convilyn_author import ToolServer\n"
            'server = ToolServer(name="t", description="t", version="0.1.0")\n'
            '@server.tool(description="test")\n'
            "async def test_tool(x: str) -> dict:\n"
            '    return {"x": x}\n'
        )

        runner = CliRunner()
        output_path = tmp_path / "manifest.json"
        result = runner.invoke(
            cli,
            [
                "synth",
                "--file",
                str(server_file),
                "--output",
                str(output_path),
            ],
        )
        assert result.exit_code == 0
        assert output_path.exists()

        manifest = json.loads(output_path.read_text())
        assert manifest["server"]["name"] == "t"
        assert len(manifest["tools"]) == 1


class TestCLITest:
    def test_local_test_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        server_file = tmp_path / "server.py"
        server_file.write_text(
            "from convilyn_author import ToolServer\n"
            'server = ToolServer(name="t", description="t", version="0.1.0")\n'
            '@server.tool(description="ping")\n'
            "async def ping() -> dict:\n"
            '    return {"pong": True}\n'
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["test", "--file", str(server_file)])
        assert result.exit_code == 0
        assert "passed" in result.output.lower()


class TestCLIDoctor:
    def test_doctor_command(self, monkeypatch):
        # A fully-configured environment passes cleanly (exit 0). The
        # no-secret / opt-in paths are covered by the dedicated tests below.
        monkeypatch.setenv("CONVILYN_HMAC_SECRET", "test-secret")  # pragma: allowlist secret
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "Python" in result.output
        assert "pydantic" in result.output


# ── _load_server_from_file error branches ─────────────────────────


class TestLoadServerFromFile:
    def test_path_outside_cwd_raises_systemexit(self, tmp_path, monkeypatch):
        # error: a file path that escapes the working directory is rejected
        monkeypatch.chdir(tmp_path)
        outside = tmp_path.parent / "evil.py"
        outside.write_text("x = 1", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_server_from_file(str(outside))

    def test_missing_file_raises_systemexit(self, tmp_path, monkeypatch):
        # error: missing server file → SystemExit (and an error message)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            _load_server_from_file("nope.py")

    def test_non_py_suffix_raises_systemexit(self, tmp_path, monkeypatch):
        # error: a .txt file in cwd is rejected as the wrong shape
        monkeypatch.chdir(tmp_path)
        (tmp_path / "server.txt").write_text("noop", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_server_from_file("server.txt")

    def test_no_tool_server_in_module_raises_systemexit(self, tmp_path, monkeypatch):
        # error: a valid .py file without a ToolServer instance is rejected
        monkeypatch.chdir(tmp_path)
        (tmp_path / "server.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_server_from_file("server.py")


# ── _load_workflow_from_file error branches ───────────────────────


class TestLoadWorkflowFromFile:
    def test_path_outside_cwd_raises_systemexit(self, tmp_path, monkeypatch):
        # error: path escape rejected (mirror of the server-loader rule)
        monkeypatch.chdir(tmp_path)
        outside = tmp_path.parent / "evil-wf.py"
        outside.write_text("x = 1", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_workflow_from_file(str(outside))

    def test_missing_file_raises_systemexit(self, tmp_path, monkeypatch):
        # error: missing workflow file → SystemExit
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            _load_workflow_from_file("nope.py")

    def test_no_workflow_in_module_raises_systemexit(self, tmp_path, monkeypatch):
        # error: valid file without a WorkflowSpec instance is rejected
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workflow.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            _load_workflow_from_file("workflow.py")


# ── dev command ────────────────────────────────────────────────────


class TestCLIDev:
    def test_dev_command_invokes_server_run(self, tmp_path, monkeypatch):
        # logic: ``dev`` resolves host/port and delegates to ToolServer.run
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path)
        runner = CliRunner()
        recorded: dict[str, object] = {}

        def fake_run(self, host=None, port=None, *, dev=False):  # type: ignore[no-untyped-def]
            recorded["host"] = host
            recorded["port"] = port
            recorded["dev"] = dev

        from convilyn_author.server import ToolServer

        monkeypatch.setattr(ToolServer, "run", fake_run)
        result = runner.invoke(
            cli,
            ["dev", "--file", "server.py", "--host", "0.0.0.0", "--port", "9001"],
        )
        assert result.exit_code == 0
        # `dev` must pass dev=True so local serving works without a secret.
        assert recorded == {"host": "0.0.0.0", "port": 9001, "dev": True}


# ── workflow init command ──────────────────────────────────────────


class TestCLIWorkflowInit:
    def test_workflow_init_scaffolds_project(self, tmp_path, monkeypatch):
        # logic: ``workflow init`` builds a workflow-type scaffold
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["workflow", "init", "wf-proj"])
        assert result.exit_code == 0
        assert "Workflow project created" in result.output
        # Next-step hints must use the real binary, not the removed `convilyn` alias.
        assert "convilyn-author workflow build" in result.output


# ── workflow build command ─────────────────────────────────────────


class TestCLIWorkflowBuild:
    def test_workflow_build_writes_spec_json(self, tmp_path, monkeypatch):
        # logic: ``workflow build`` compiles + writes the spec JSON
        monkeypatch.chdir(tmp_path)
        _write_workflow(tmp_path)
        _write_server(tmp_path)
        runner = CliRunner()
        output_path = tmp_path / "wf.spec.json"
        result = runner.invoke(
            cli,
            [
                "workflow",
                "build",
                "--file",
                "workflow.py",
                "--server-file",
                "server.py",
                "--output",
                str(output_path),
            ],
        )
        assert result.exit_code == 0
        assert output_path.exists()

    def test_workflow_build_without_server_file_still_compiles(
        self,
        tmp_path,
        monkeypatch,
    ):
        # boundary: when server.py is absent, tool-coverage validation is skipped
        monkeypatch.chdir(tmp_path)
        _write_workflow(tmp_path)
        runner = CliRunner()
        output_path = tmp_path / "wf.spec.json"
        result = runner.invoke(
            cli,
            [
                "workflow",
                "build",
                "--file",
                "workflow.py",
                "--server-file",
                "absent.py",
                "--output",
                str(output_path),
            ],
        )
        assert result.exit_code == 0


# ── push command ───────────────────────────────────────────────────


class _FakeAsyncClient:
    """Stand-in for ConvilynClient that records the push payload."""

    last_push: dict | None = None

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def push(self, *, server, workflow, endpoint_url):  # type: ignore[no-untyped-def]
        type(self).last_push = {
            "server_name": server.name,
            "endpoint_url": endpoint_url,
        }
        return {
            "server_id": "srv-123",
            "server_status": "pending",
            "workflow_id": "wf-456",
            "workflow_status": "pending",
        }

    async def list_servers(self) -> list[dict]:
        return [{"server_name": "srv-a", "server_id": "id-a", "status": "verified"}]

    async def list_workflows(self) -> list[dict]:
        return [{"name": "wf-a", "workflow_id": "wid-a", "status": "active"}]


class TestCLIPush:
    def test_push_invokes_client_and_prints_ids(
        self,
        tmp_path,
        monkeypatch,
    ):
        # logic: ``push`` calls ConvilynClient.push and surfaces returned IDs
        monkeypatch.chdir(tmp_path)
        _write_server(tmp_path)
        _write_workflow(tmp_path)
        # Patch the ConvilynClient symbol at the import site inside push().
        monkeypatch.setattr(
            "convilyn_author.client.ConvilynClient",
            _FakeAsyncClient,
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "push",
                "--server-file",
                "server.py",
                "--workflow-file",
                "workflow.py",
                "--endpoint-url",
                "https://example.test",
            ],
        )
        assert result.exit_code == 0
        assert "srv-123" in result.output


# ── status command ─────────────────────────────────────────────────


class TestCLIStatus:
    def test_status_lists_servers_and_workflows(self, monkeypatch):
        # logic: ``status`` prints both server + workflow rows
        monkeypatch.setattr(
            "convilyn_author.client.ConvilynClient",
            _FakeAsyncClient,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "srv-a" in result.output
        assert "wf-a" in result.output

    def test_status_handles_empty_response(self, monkeypatch):
        # boundary: empty lists yield the "No servers / No workflows" messages
        class _Empty(_FakeAsyncClient):
            async def list_servers(self) -> list[dict]:
                return []

            async def list_workflows(self) -> list[dict]:
                return []

        monkeypatch.setattr(
            "convilyn_author.client.ConvilynClient",
            _Empty,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No servers submitted" in result.output

    def test_status_handles_client_error(self, monkeypatch):
        # error: ConvilynClientError surfaces a non-zero exit + error message
        from convilyn_author.client import ConvilynClientError

        class _Failing(_FakeAsyncClient):
            async def list_servers(self) -> list[dict]:
                raise ConvilynClientError(status_code=500, detail="boom")

        monkeypatch.setattr(
            "convilyn_author.client.ConvilynClient",
            _Failing,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code != 0
        assert "boom" in result.output


# ── doctor command — extra branches ────────────────────────────────


class TestCLIDoctorBranches:
    def test_doctor_reports_missing_core_dependency(self, monkeypatch):
        # error: a missing core dep triggers a [FAIL] line and exit code 1
        import importlib

        original_import_module = importlib.import_module

        def fake_import_module(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "pydantic":
                raise ImportError("simulated absence")
            return original_import_module(name, *args, **kwargs)

        monkeypatch.setattr(
            "convilyn_author.cli.main.importlib.import_module",
            fake_import_module,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert "[FAIL] pydantic" in result.output

    def test_doctor_reports_missing_optional_dependency(self, monkeypatch):
        # boundary: missing optional dep is reported as [SKIP], not [FAIL]
        import importlib

        original_import_module = importlib.import_module

        def fake_import_module(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "boto3":
                raise ImportError("simulated absence")
            return original_import_module(name, *args, **kwargs)

        monkeypatch.setattr(
            "convilyn_author.cli.main.importlib.import_module",
            fake_import_module,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert "[SKIP] boto3" in result.output

    def test_doctor_warns_when_dev_insecure_optin(self, monkeypatch):
        # boundary: insecure-dev opt-in + no HMAC secret → [WARN], not [FAIL].
        # `is_local` alone no longer warns — auth is fail-closed.
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)
        monkeypatch.setenv("CONVILYN_ENVIRONMENT", "local")
        monkeypatch.setenv("CONVILYN_DEV_INSECURE", "1")
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert "[WARN] CONVILYN_HMAC_SECRET" in result.output

    def test_doctor_fails_when_hmac_unset_and_no_optin(self, monkeypatch):
        # error: no secret + no insecure-dev opt-in → server refuses to
        # start → [FAIL] + exit 1, even in a local environment.
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)
        monkeypatch.delenv("CONVILYN_DEV_INSECURE", raising=False)
        monkeypatch.setenv("CONVILYN_ENVIRONMENT", "local")
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code != 0
        assert "[FAIL] CONVILYN_HMAC_SECRET" in result.output

    def test_doctor_fails_when_hmac_unset_outside_dev(self, monkeypatch):
        # error: non-local env without HMAC_SECRET → [FAIL] + exit 1
        monkeypatch.delenv("CONVILYN_HMAC_SECRET", raising=False)
        monkeypatch.delenv("CONVILYN_DEV_INSECURE", raising=False)
        monkeypatch.setenv("CONVILYN_ENVIRONMENT", "production")
        monkeypatch.setenv("CONVILYN_HOST", "0.0.0.0")
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code != 0
        assert "[FAIL] CONVILYN_HMAC_SECRET" in result.output


# ── _run_local_test failure path ───────────────────────────────────


class TestCLITestFailureExit:
    def test_test_command_exits_nonzero_when_compliance_fails(
        self,
        tmp_path,
        monkeypatch,
    ):
        # error: a compliance check failure surfaces as exit code 1
        monkeypatch.chdir(tmp_path)
        # A server with a tool whose signature breaks JSON-Schema derivation
        # (positional-only kwargs are unsupported by the schema builder).
        (tmp_path / "server.py").write_text(
            "from convilyn_author import ToolServer\n"
            'server = ToolServer(name="t", description="t", version="0.1.0")\n',
            encoding="utf-8",
        )
        # Force the runner to report a failing check by patching
        # ConvilynTestRunner.run_compliance_check on the imported module.
        from convilyn_author.testing import runner as runner_mod
        from convilyn_author.types import ComplianceReport, ComplianceResult

        async def failing_check(self):  # type: ignore[no-untyped-def]
            return ComplianceReport(
                results=[
                    ComplianceResult(
                        passed=False,
                        check_name="forced-failure",
                        message="forced",
                    ),
                ],
            )

        monkeypatch.setattr(
            runner_mod.ConvilynTestRunner,
            "run_compliance_check",
            failing_check,
        )
        cli_runner = CliRunner()
        result = cli_runner.invoke(cli, ["test", "--file", "server.py"])
        assert result.exit_code != 0
        assert "failed" in result.output.lower()
