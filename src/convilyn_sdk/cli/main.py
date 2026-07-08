"""Convilyn CLI — init, synth, dev, test, doctor."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import click

from convilyn_sdk._internal.server_runtime import _dev_insecure_requested
from convilyn_sdk._version import __version__
from convilyn_sdk.config import SDKConfig


def _load_server_from_file(path: str = "server.py") -> Any:
    """Dynamically load a ToolServer from a Python file."""
    file_path = Path(path).resolve()

    # Restrict to current working directory to prevent loading arbitrary files
    cwd = Path.cwd().resolve()
    try:
        file_path.relative_to(cwd)
    except ValueError:
        click.echo(
            f"Error: {path} is outside the current working directory. "
            "Server files must be within your project directory.",
            err=True,
        )
        raise SystemExit(1)

    if not file_path.exists():
        click.echo(f"Error: {path} not found", err=True)
        raise SystemExit(1)

    if not file_path.suffix == ".py":
        click.echo("Error: Server file must be a .py file", err=True)
        raise SystemExit(1)

    spec = importlib.util.spec_from_file_location("_user_server", str(file_path))
    if spec is None or spec.loader is None:
        click.echo(f"Error: Cannot load {path}", err=True)
        raise SystemExit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from convilyn_sdk.server import ToolServer

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, ToolServer):
            return attr

    click.echo(f"Error: No ToolServer instance found in {path}", err=True)
    raise SystemExit(1)


@click.group()
@click.version_option(
    version=__version__,
    prog_name="convilyn-author",
    message="%(prog)s %(version)s",
)
def cli() -> None:
    """Convilyn SDK — Build tool servers for the Convilyn AI workflow platform."""


@cli.command()
@click.argument("name")
@click.option("--dir", "target_dir", default=None, help="Target directory")
def init(name: str, target_dir: str | None) -> None:
    """Scaffold a new Convilyn server project."""
    from convilyn_sdk.cli.scaffold import scaffold_project

    out = scaffold_project(name, Path(target_dir) if target_dir else None)
    click.echo(f"Project created: {out}")
    click.echo(f"  cd {out.name}")
    click.echo("  pip install convilyn-author")
    click.echo("  convilyn-author dev")


@cli.command()
@click.option("--file", "server_file", default="server.py", help="Server definition file")
@click.option("--output", default="convilyn.manifest.json", help="Output manifest path")
def synth(server_file: str, output: str) -> None:
    """Compile server definition into a manifest blueprint."""
    server = _load_server_from_file(server_file)
    manifest = server.synth()

    click.echo("Scanning server definition...")
    click.echo(f"Found {len(manifest.tools)} tool(s): {', '.join(t.name for t in manifest.tools)}")

    manifest.save(output)
    click.echo(f"Blueprint generated: {output}")


@cli.command()
@click.option("--file", "server_file", default="server.py", help="Server definition file")
@click.option("--host", default=None, help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to")
def dev(server_file: str, host: str | None, port: int | None) -> None:
    """Start the server locally for development.

    Runs in INSECURE mode (``dev=True``): inbound ``/mcp`` requests are
    served without HMAC verification when no ``CONVILYN_HMAC_SECRET`` is
    set, so local iteration stays friction-free. Deployed servers must
    set the secret — ``ToolServer.run()`` is fail-closed by default.
    """
    server = _load_server_from_file(server_file)
    config = SDKConfig.from_env()
    server.run(
        host=host or config.server_host,
        port=port or config.server_port,
        dev=True,
    )


@cli.command()
@click.option("--file", "server_file", default="server.py", help="Server definition file")
def test(server_file: str) -> None:
    """Run local validation tests on the server."""
    _run_local_test(server_file)


def _run_local_test(server_file: str) -> None:
    """Run local compliance checks."""
    from convilyn_sdk.testing.runner import ConvilynTestRunner

    server = _load_server_from_file(server_file)
    runner = ConvilynTestRunner(server=server)

    click.echo("Running local compliance checks...")
    report = asyncio.run(runner.run_compliance_check())

    for result in report.results:
        icon = "PASS" if result.passed else "FAIL"
        click.echo(f"  [{icon}] {result.check_name}: {result.message}")

    click.echo()
    if report.all_passed:
        click.echo(f"All {len(report.results)} checks passed")
    else:
        click.echo(f"{len(report.failed)} of {len(report.results)} checks failed")
        raise SystemExit(1)


@cli.group()
def workflow() -> None:
    """Workflow definition and management commands."""


@workflow.command("init")
@click.argument("name")
@click.option("--dir", "target_dir", default=None, help="Target directory")
def workflow_init(name: str, target_dir: str | None) -> None:
    """Scaffold a new Convilyn workflow project (tools + workflow spec)."""
    from convilyn_sdk.cli.scaffold import scaffold_project

    out = scaffold_project(name, Path(target_dir) if target_dir else None, project_type="workflow")
    click.echo(f"Workflow project created: {out}")
    click.echo(f"  cd {out.name}")
    click.echo("  pip install convilyn-author")
    click.echo("  # Edit server.py (define tools) and workflow.py (define workflow)")
    click.echo("  convilyn-author workflow build")
    click.echo("  convilyn-author test")


@workflow.command("build")
@click.option("--file", "workflow_file", default="workflow.py", help="Workflow definition file")
@click.option("--server-file", default="server.py", help="Server definition file")
@click.option("--output", default="workflow.spec.json", help="Output spec path")
def workflow_build(workflow_file: str, server_file: str, output: str) -> None:
    """Compile workflow spec and validate tool coverage."""
    from convilyn_sdk.workflow_validator import validate_tool_coverage, validate_workflow_spec

    # Load workflow
    workflow_obj = _load_workflow_from_file(workflow_file)

    # Compile
    compiled = workflow_obj.compile()
    click.echo(f"Compiled workflow: {compiled.get('name', '?')} ({compiled.get('spec_id', '?')})")

    # Validate spec structure
    spec_result = validate_workflow_spec(compiled)
    for err in spec_result.errors:
        click.echo(f"  [ERROR] {err}", err=True)
    for warn in spec_result.warnings:
        click.echo(f"  [WARN] {warn}")

    if not spec_result.valid:
        click.echo("Spec validation failed", err=True)
        raise SystemExit(1)

    # Validate tool coverage if server.py exists
    server_path = Path(server_file).resolve()
    if server_path.exists():
        server = _load_server_from_file(server_file)
        tool_result = validate_tool_coverage(compiled, [server])
        for err in tool_result.errors:
            click.echo(f"  [ERROR] {err}", err=True)
        for warn in tool_result.warnings:
            click.echo(f"  [WARN] {warn}")
        if not tool_result.valid:
            click.echo("Tool coverage validation failed", err=True)
            raise SystemExit(1)

    # Save
    import json

    Path(output).write_text(
        json.dumps(compiled, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    mcp_tools = compiled.get("mcp_config", {}).get("tools", [])
    phases = compiled.get("phases", [])
    click.echo(f"  Tools: {len(mcp_tools)}, Phases: {len(phases)}")
    click.echo(f"Spec written: {output}")


@cli.command()
@click.option("--server-file", default="server.py", help="Server definition file")
@click.option("--workflow-file", default="workflow.py", help="Workflow definition file")
@click.option("--endpoint-url", required=True, help="HTTPS URL where server is deployed")
def push(server_file: str, workflow_file: str, endpoint_url: str) -> None:
    """Push tool server and workflow to the Convilyn platform."""
    from convilyn_sdk.client import ConvilynClient

    server = _load_server_from_file(server_file)
    workflow_obj = _load_workflow_from_file(workflow_file)

    client = ConvilynClient()

    async def _push() -> dict:
        return await client.push(
            server=server,
            workflow=workflow_obj,
            endpoint_url=endpoint_url,
        )

    click.echo("Pushing to Convilyn platform...")
    result = asyncio.run(_push())

    server_id = result.get("server_id", "?")
    server_status = result.get("server_status", "?")
    workflow_id = result.get("workflow_id", "?")
    workflow_status = result.get("workflow_status", "?")
    click.echo(f"Server submitted: {server_id} ({server_status})")
    click.echo(f"Workflow submitted: {workflow_id} ({workflow_status})")
    click.echo("Use 'convilyn-author status' to check verification progress.")


@cli.command()
@click.option("--server-file", default="server.py", help="Server definition file")
@click.option(
    "--workflow-file",
    default="workflow.py",
    help="Workflow definition file (optional — omit to deploy server only)",
)
@click.option(
    "--hosted",
    is_flag=True,
    default=False,
    help="Deploy to the Convilyn-Hosted Author Runtime (vs BYO `push --endpoint-url`)",
)
@click.option(
    "--region",
    default="us-east-1",
    help="region the hosted runtime is provisioned in",
)
def deploy(server_file: str, workflow_file: str, hosted: bool, region: str) -> None:
    """Deploy a tool server to the Convilyn platform.

    With ``--hosted``, Convilyn provisions a sandboxed hosted runtime in its
    own AWS account and returns the public endpoint URL — the author
    never runs their own infrastructure. Pairs with ``rollback`` and
    ``logs`` for lifecycle operations.

    Without ``--hosted``, the command errors and points at ``push``;
    BYO deployments stay on the existing ``convilyn-author push
    --endpoint-url ...`` flow so a single subcommand never has two
    distinct meanings.
    """
    if not hosted:
        click.echo(
            "Error: `deploy` currently requires --hosted. Use "
            "`convilyn-author push --endpoint-url <https://...>` for "
            "caller-deployed (BYO) servers.",
            err=True,
        )
        raise SystemExit(1)

    from convilyn_sdk.client import ConvilynClient, ConvilynClientError

    server = _load_server_from_file(server_file)
    manifest = server.synth().to_dict()

    workflow_spec_dict: dict[str, Any] | None = None
    if Path(workflow_file).resolve().exists():
        workflow_obj = _load_workflow_from_file(workflow_file)
        workflow_spec_dict = workflow_obj.compile()

    client = ConvilynClient()

    async def _deploy() -> dict[str, Any]:
        return await client.deploy_hosted_runtime(
            manifest, region=region, workflow_spec=workflow_spec_dict
        )

    click.echo(f"Deploying to Convilyn-Hosted Runtime in {region}...")
    try:
        result = asyncio.run(_deploy())
    except ConvilynClientError as e:
        if e.status_code == 501:
            click.echo(
                f"Error: hosted runtime not yet available on this platform "
                f"({e.detail}). Use `convilyn-author push --endpoint-url ...` "
                f"as a BYO fallback.",
                err=True,
            )
        else:
            click.echo(f"Error: {e.detail}", err=True)
        raise SystemExit(1)

    runtime_id = result.get("runtime_id", "?")
    endpoint_url = result.get("endpoint_url", "?")
    status = result.get("status", "?")
    click.echo(f"Runtime provisioned: {runtime_id} ({status})")
    click.echo(f"Endpoint URL: {endpoint_url}")
    if workflow_spec_dict and "workflow_id" in result:
        click.echo(f"Workflow registered: {result['workflow_id']}")
    click.echo(
        "Use 'convilyn-author logs <runtime_id>' to follow runtime logs, "
        "'convilyn-author rollback <runtime_id>' to revert."
    )


@cli.command()
@click.argument("runtime_id")
def rollback(runtime_id: str) -> None:
    """Roll a hosted runtime back to its previous active version.

    The hosted runtime atomically flips; subsequent rollbacks continue
    stepping back through the kept image history (lifecycle policy
    retains the most recent versions).
    """
    from convilyn_sdk.client import ConvilynClient, ConvilynClientError

    client = ConvilynClient()

    async def _rollback() -> dict[str, Any]:
        return await client.rollback_hosted_runtime(runtime_id)

    click.echo(f"Rolling back {runtime_id}...")
    try:
        result = asyncio.run(_rollback())
    except ConvilynClientError as e:
        click.echo(f"Error: {e.detail}", err=True)
        raise SystemExit(1)

    version = result.get("version", "?")
    status = result.get("status", "?")
    click.echo(f"Rollback complete: now-active version {version} ({status})")


@cli.command()
@click.argument("runtime_id")
@click.option(
    "--since",
    default=None,
    help="Relative window (e.g. '5m', '1h') or ISO-8601 timestamp",
)
@click.option("--limit", default=100, type=int, help="Maximum log entries to fetch")
def logs(runtime_id: str, since: str | None, limit: int) -> None:
    """Fetch recent logs for a hosted runtime."""
    from convilyn_sdk.client import ConvilynClient, ConvilynClientError

    client = ConvilynClient()

    async def _logs() -> list[dict[str, Any]]:
        return await client.get_hosted_runtime_logs(runtime_id, since=since, limit=limit)

    try:
        entries = asyncio.run(_logs())
    except ConvilynClientError as e:
        click.echo(f"Error: {e.detail}", err=True)
        raise SystemExit(1)

    if not entries:
        click.echo(f"No log entries for {runtime_id} in the requested window.")
        return
    for entry in entries:
        ts = entry.get("timestamp", "?")
        level = entry.get("level", "INFO")
        message = entry.get("message", "")
        click.echo(f"[{ts}] {level} {message}")


@cli.group("template")
def template() -> None:
    """Template marketplace — discover, install, and fork community templates.

    Templates live under the ``convilyn-template-*`` PyPI namespace
    and are how authors share fully-formed workflow
    starters. Pairs with the existing R4 web marketplace (DynamoDB-
    backed UI for end users); this CLI surface is the Git-workflow
    counterpart for authors.
    """


@template.command("list")
@click.option(
    "--query",
    default=None,
    help="Case-insensitive substring filter on the template suffix",
)
def template_list(query: str | None) -> None:
    """List published ``convilyn-template-*`` packages on PyPI."""
    from convilyn_sdk._internal.templates import TemplateError, list_templates

    try:
        packages = list_templates(query=query)
    except TemplateError as exc:
        click.echo(f"Error: {exc} ({exc.code})", err=True)
        raise SystemExit(1)

    if not packages:
        click.echo(
            "No templates found. The convilyn-template-* namespace is "
            "brand-new; ask the community channel for a starter or "
            "publish your own under that prefix."
        )
        return
    for pkg in packages:
        click.echo(pkg)


@template.command("install")
@click.argument("name")
def template_install(name: str) -> None:
    """Install ``convilyn-template-<name>`` via pip and record it locally."""
    from convilyn_sdk._internal.templates import TemplateError, install_template

    try:
        entry = install_template(name)
    except TemplateError as exc:
        click.echo(f"Error: {exc} ({exc.code})", err=True)
        raise SystemExit(1)

    click.echo(f"Installed {entry.package}=={entry.version}")
    if entry.source:
        click.echo(f"Source: {entry.source}")


@template.command("fork")
@click.argument("name")
@click.argument("new_name")
def template_fork(name: str, new_name: str) -> None:
    """Clone the template's source repo and rewrite it under ``new_name``."""
    from convilyn_sdk._internal.templates import TemplateError, fork_template

    try:
        destination = fork_template(name, new_name)
    except TemplateError as exc:
        click.echo(f"Error: {exc} ({exc.code})", err=True)
        raise SystemExit(1)

    click.echo(f"Forked to {destination}")
    click.echo(f"Next:\n  cd {destination.name}\n  pip install -e .\n  convilyn-author dev")


@cli.command("status")
def check_status() -> None:
    """Check submission status of servers and workflows."""
    from convilyn_sdk.client import ConvilynClient, ConvilynClientError

    client = ConvilynClient()

    async def _status() -> None:
        try:
            servers = await client.list_servers()
            if servers:
                click.echo("Servers:")
                for srv in servers:
                    click.echo(
                        f"  {srv.get('server_name', '?')} "
                        f"({srv.get('server_id', '?')}) — {srv.get('status', '?')}"
                    )
            else:
                click.echo("No servers submitted.")

            workflows = await client.list_workflows()
            if workflows:
                click.echo("Workflows:")
                for wf in workflows:
                    click.echo(
                        f"  {wf.get('name', wf.get('spec_id', '?'))} "
                        f"({wf.get('workflow_id', '?')}) — {wf.get('status', '?')}"
                    )
            else:
                click.echo("No workflows submitted.")
        except ConvilynClientError as e:
            click.echo(f"Error: {e.detail}", err=True)
            raise SystemExit(1)

    asyncio.run(_status())


def _load_workflow_from_file(path: str = "workflow.py") -> Any:
    """Dynamically load a WorkflowSpec from a Python file."""
    file_path = Path(path).resolve()

    cwd = Path.cwd().resolve()
    try:
        file_path.relative_to(cwd)
    except ValueError:
        click.echo(
            f"Error: {path} is outside the current working directory.",
            err=True,
        )
        raise SystemExit(1)

    if not file_path.exists():
        click.echo(f"Error: {path} not found", err=True)
        raise SystemExit(1)

    spec = importlib.util.spec_from_file_location("_user_workflow", str(file_path))
    if spec is None or spec.loader is None:
        click.echo(f"Error: Cannot load {path}", err=True)
        raise SystemExit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from convilyn_sdk.workflow import WorkflowSpec

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, WorkflowSpec):
            return attr

    click.echo(f"Error: No WorkflowSpec instance found in {path}", err=True)
    raise SystemExit(1)


@cli.command()
def doctor() -> None:
    """Check environment and configuration health."""
    import platform

    issues: list[str] = []

    # Python version
    py_version = platform.python_version()
    py_major, py_minor = sys.version_info[:2]
    if py_major < 3 or (py_major == 3 and py_minor < 10):
        issues.append(f"Python 3.10+ required, got {py_version}")
        click.echo(f"  [FAIL] Python: {py_version}")
    else:
        click.echo(f"  [OK] Python: {py_version}")

    # Core dependencies
    for pkg in ["pydantic", "click", "uvicorn", "httpx"]:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "unknown")
            click.echo(f"  [OK] {pkg}: {ver}")
        except ImportError:
            issues.append(f"Missing dependency: {pkg}")
            click.echo(f"  [FAIL] {pkg}: not installed")

    # Optional dependencies
    for pkg in ["boto3"]:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "unknown")
            click.echo(f"  [OK] {pkg}: {ver} (optional)")
        except ImportError:
            click.echo(f"  [SKIP] {pkg}: not installed (optional, needed for production)")

    # Config
    config = SDKConfig.from_env()
    click.echo(f"  [OK] Host: {config.server_host}")
    click.echo(f"  [OK] Port: {config.server_port}")
    click.echo(f"  [OK] Environment: {config.environment}")
    click.echo(f"  [OK] Is local: {config.is_local}")

    # HMAC inbound-signature verification. Fail-closed: a missing secret
    # makes the server refuse to start UNLESS insecure dev is opted into
    # (CONVILYN_DEV_INSECURE / `convilyn-author dev`). `is_local` is NOT an
    # auth signal, so it must not gate this diagnostic.
    if config.hmac_secret:
        click.echo("  [OK] CONVILYN_HMAC_SECRET: set (inbound verification enabled)")
    elif _dev_insecure_requested():
        click.echo(
            "  [WARN] CONVILYN_HMAC_SECRET: not set "
            "(CONVILYN_DEV_INSECURE opt-in — /mcp accepts unsigned requests)"
        )
    else:
        issues.append(
            "CONVILYN_HMAC_SECRET is not set: the server refuses to start. "
            "Set it, or set CONVILYN_DEV_INSECURE=1 (or run `convilyn-author "
            "dev`) for insecure local development."
        )
        click.echo(
            "  [FAIL] CONVILYN_HMAC_SECRET: not set "
            "(server will refuse to start; set the secret or CONVILYN_DEV_INSECURE=1)"
        )

    click.echo()
    if issues:
        click.echo(f"{len(issues)} issue(s) found")
        for issue in issues:
            click.echo(f"  - {issue}")
        raise SystemExit(1)
    else:
        click.echo("All checks passed")
