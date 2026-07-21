"""Project scaffolding — generates starter server projects."""

from __future__ import annotations

from pathlib import Path

SERVER_PY_TEMPLATE = '''\
"""Convilyn tool server — {name}."""

from convilyn_author import ToolServer

server = ToolServer(
    name="{name}",
    description="TODO: Describe your server",
    version="0.1.0",
)


@server.tool(description="TODO: Describe this tool")
async def example_tool(input_text: str) -> dict:
    """Example tool — replace with your implementation."""
    result = {{"processed": input_text, "length": len(input_text)}}
    ref_id = await server.data_store.store(result)
    return {{"ref_id": ref_id, "summary": f"Processed {{len(input_text)}} chars"}}


if __name__ == "__main__":
    server.run()
'''

PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "convilyn-author>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
]
"""

TEST_TEMPLATE = '''\
"""Tests for {name} server."""

import pytest
from convilyn_author.testing import ConvilynTestRunner

from server import server


@pytest.fixture
def runner():
    return ConvilynTestRunner(server=server)


@pytest.mark.asyncio
async def test_example_tool(runner):
    result = await runner.call_tool("example_tool", {{"input_text": "hello"}})
    assert result.success
    assert "ref_id" in result.data
    assert "summary" in result.data


@pytest.mark.asyncio
async def test_compliance(runner):
    report = await runner.run_compliance_check()
    assert report.all_passed, f"Failed checks: {{report.failed}}"
'''

GITIGNORE_TEMPLATE = """\
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
convilyn.manifest.json
.env
"""

ENV_EXAMPLE_TEMPLATE = """\
# Convilyn SDK configuration
CONVILYN_HOST=127.0.0.1
CONVILYN_PORT=8080
CONVILYN_LOG_LEVEL=INFO
CONVILYN_ENVIRONMENT=local

# Your own secrets (SDK does NOT manage these)
# MY_API_KEY=
"""

WORKFLOW_SERVER_PY_TEMPLATE = '''\
"""Convilyn tool server — {name}."""

from convilyn_author import ToolServer

server = ToolServer(
    name="{name}",
    description="TODO: Describe your server",
    version="0.1.0",
)


@server.tool(description="TODO: Describe this tool")
async def process(input_text: str, language: str = "en") -> dict:
    """Process input — replace with your implementation."""
    result = {{"processed": input_text, "language": language, "length": len(input_text)}}
    ref_id = await server.data_store.store(result)
    return {{"ref_id": ref_id, "summary": f"Processed {{len(input_text)}} chars"}}


@server.tool(description="TODO: Describe this tool")
async def summarize(input_text: str) -> dict:
    """Summarize input — replace with your implementation."""
    summary = input_text[:200] + "..." if len(input_text) > 200 else input_text
    return {{"summary": summary, "original_length": len(input_text)}}


if __name__ == "__main__":
    server.run()
'''

WORKFLOW_PY_TEMPLATE = '''\
"""Convilyn workflow definition — {name}."""

from convilyn_author import WorkflowSpec

# Import server to auto-populate tool references
from server import server

workflow = (
    WorkflowSpec(
        "{name}",
        name="TODO: Workflow Display Name",
        version="0.1.0",
        description="TODO: Describe what this workflow does",
    )
    .with_input(
        types=["document"],
        formats=["pdf", "txt"],
        max_size_bytes=10_485_760,
    )
    .with_output(format="json", type="analysis_result")
    .from_server(server)
    .add_phase(
        "Process",
        "Extract and process the uploaded document using "
        "`{name_under}__process`.",
    )
    .add_phase(
        "Summarize",
        "Generate a summary using `{name_under}__summarize`. "
        "Store the result via `store_artifact`.",
    )
    .add_phase(
        "Complete",
        "Call `complete_workflow` with a summary of what was produced.",
    )
    .with_agent_config(max_iterations=20, temperature=0.3)
    .add_preflight_rule(
        "check_has_file",
        check_type="file_count",
        params={{"type": "document", "min": 1}},
        error_message="Please upload a document",
    )
    .with_locale_policy(type="locale_independent")
)

if __name__ == "__main__":
    import json
    print(json.dumps(workflow.compile(), indent=2))
'''

WORKFLOW_TEST_TEMPLATE = '''\
"""Tests for {name} workflow."""

import pytest
from convilyn_author.testing import ConvilynTestRunner, WorkflowTestRunner

from server import server
from workflow import workflow


@pytest.fixture
def tool_runner():
    return ConvilynTestRunner(server=server)


@pytest.fixture
def workflow_runner():
    return WorkflowTestRunner(workflow=workflow, tool_servers=[server])


@pytest.mark.asyncio
async def test_tool_compliance(tool_runner):
    report = await tool_runner.run_compliance_check()
    assert report.all_passed, f"Failed checks: {{report.failed}}"


@pytest.mark.asyncio
async def test_workflow_spec_valid(workflow_runner):
    result = await workflow_runner.validate_spec()
    assert result.valid, f"Spec errors: {{result.errors}}"


@pytest.mark.asyncio
async def test_workflow_tool_chain(workflow_runner):
    result = await workflow_runner.validate_tool_chain()
    assert result.valid, f"Tool chain errors: {{result.errors}}"


@pytest.mark.asyncio
async def test_workflow_dry_run(workflow_runner):
    result = await workflow_runner.run(mode="dry_run")
    assert result.passed, f"Dry run errors: {{result.errors}}"
'''

DOCKERFILE_TEMPLATE = """\
FROM public.ecr.aws/lambda/python:3.12

COPY --from=public.ecr.aws/awsguru/aws-lambda-web-adapter:0.8.4 \\
    /lambda-adapter /opt/extensions/lambda-adapter

ENV PORT=8080
ENV AWS_LWA_INVOKE_MODE=response_stream
ENV AWS_LWA_READINESS_CHECK_PATH=/health

WORKDIR ${{LAMBDA_TASK_ROOT}}

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
"""


def scaffold_project(
    name: str,
    target_dir: Path | None = None,
    project_type: str = "tools",
) -> Path:
    """Generate a starter Convilyn project.

    Args:
        name: Project/server name (used in filenames and metadata).
        target_dir: Directory to create the project in. Defaults to ./{name}.
        project_type: "tools" for tool-only project, "workflow" for full workflow project.

    Returns:
        Path to the created project directory.
    """
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise ValueError(
            f"Invalid project name '{name}'. "
            "Use only alphanumeric characters, hyphens, and underscores."
        )

    project_dir = target_dir or Path.cwd() / name
    project_dir.mkdir(parents=True, exist_ok=True)

    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    name_under = name.replace("-", "_")

    if project_type == "workflow":
        # Workflow project: server.py + workflow.py + workflow tests
        (project_dir / "server.py").write_text(
            WORKFLOW_SERVER_PY_TEMPLATE.format(name=name), encoding="utf-8"
        )
        (project_dir / "workflow.py").write_text(
            WORKFLOW_PY_TEMPLATE.format(name=name, name_under=name_under),
            encoding="utf-8",
        )
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / f"test_{name_under}.py").write_text(
            WORKFLOW_TEST_TEMPLATE.format(name=name), encoding="utf-8"
        )
    else:
        # Tool-only project: server.py + tool tests
        (project_dir / "server.py").write_text(
            SERVER_PY_TEMPLATE.format(name=name), encoding="utf-8"
        )
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / f"test_{name_under}.py").write_text(
            TEST_TEMPLATE.format(name=name), encoding="utf-8"
        )

    (project_dir / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(name=name), encoding="utf-8"
    )
    (project_dir / ".gitignore").write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
    (project_dir / ".env.example").write_text(ENV_EXAMPLE_TEMPLATE, encoding="utf-8")
    (project_dir / "Dockerfile").write_text(DOCKERFILE_TEMPLATE, encoding="utf-8")

    return project_dir
