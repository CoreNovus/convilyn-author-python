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
) -> Path:
    """Generate a starter Convilyn tool-server project.

    Args:
        name: Project/server name (used in filenames and metadata).
        target_dir: Directory to create the project in. Defaults to ./{name}.

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

    (project_dir / "server.py").write_text(SERVER_PY_TEMPLATE.format(name=name), encoding="utf-8")
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
