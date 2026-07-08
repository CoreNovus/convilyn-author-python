"""CLI tests for the R9 template-marketplace subcommands.

Covers ``convilyn-author template list``, ``install``, and ``fork``.
The underlying templates module is mocked at its public seam so the
CLI tests focus on argument parsing + output, not network behaviour
(unit tests for the network path live in
``tests/unit/_internal/test_templates.py``).
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from convilyn_sdk._internal.templates import TemplateEntry, TemplateError
from convilyn_sdk.cli.main import cli

# ── 1. Logic — list happy path ────────────────────────────────


class TestTemplateListCli:
    def test_list_prints_packages(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.list_templates",
            return_value=["convilyn-template-blog", "convilyn-template-newsletter"],
        ):
            result = runner.invoke(cli, ["template", "list"])
        assert result.exit_code == 0, result.output
        assert "convilyn-template-blog" in result.output
        assert "convilyn-template-newsletter" in result.output

    def test_list_empty_namespace_prints_friendly_message(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.list_templates",
            return_value=[],
        ):
            result = runner.invoke(cli, ["template", "list"])
        assert result.exit_code == 0
        assert "brand-new" in result.output or "No templates found" in result.output

    def test_list_query_forwarded(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.list_templates",
            return_value=[],
        ) as fn:
            runner.invoke(cli, ["template", "list", "--query", "blog"])
        fn.assert_called_once_with(query="blog")


# ── 2. Boundary — list network failure ────────────────────────


class TestTemplateListCliError:
    def test_pypi_unavailable_exits_1(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.list_templates",
            side_effect=TemplateError("PyPI down", code="PYPI_UNAVAILABLE"),
        ):
            result = runner.invoke(cli, ["template", "list"])
        assert result.exit_code == 1
        assert "PYPI_UNAVAILABLE" in result.output


# ── 3. install ────────────────────────────────────────────────


class TestTemplateInstallCli:
    def test_install_success_reports_entry(self) -> None:
        entry = TemplateEntry(
            name="blog",
            package="convilyn-template-blog",
            version="0.4.2",
            source="https://github.com/example/blog",
        )
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.install_template",
            return_value=entry,
        ) as fn:
            result = runner.invoke(cli, ["template", "install", "blog"])
        assert result.exit_code == 0, result.output
        assert "convilyn-template-blog==0.4.2" in result.output
        assert "github.com/example/blog" in result.output
        fn.assert_called_once_with("blog")

    def test_install_failure_surfaces_code(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.install_template",
            side_effect=TemplateError("pip 1", code="PIP_FAILED"),
        ):
            result = runner.invoke(cli, ["template", "install", "missing"])
        assert result.exit_code == 1
        assert "PIP_FAILED" in result.output

    def test_install_omits_source_line_when_absent(self) -> None:
        entry = TemplateEntry(
            name="solo",
            package="convilyn-template-solo",
            version="0.1.0",
            source=None,
        )
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.install_template",
            return_value=entry,
        ):
            result = runner.invoke(cli, ["template", "install", "solo"])
        assert result.exit_code == 0
        assert "Source:" not in result.output


# ── 4. fork ───────────────────────────────────────────────────


class TestTemplateForkCli:
    def test_fork_success_prints_destination(self, tmp_path) -> None:
        destination = tmp_path / "my-blog"
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.fork_template",
            return_value=destination,
        ) as fn:
            result = runner.invoke(cli, ["template", "fork", "blog", "my-blog"])
        assert result.exit_code == 0, result.output
        assert "my-blog" in result.output
        fn.assert_called_once_with("blog", "my-blog")

    def test_fork_destination_exists_surfaces_code(self, tmp_path) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.fork_template",
            side_effect=TemplateError("Destination exists", code="DESTINATION_EXISTS"),
        ):
            result = runner.invoke(cli, ["template", "fork", "blog", "my-blog"])
        assert result.exit_code == 1
        assert "DESTINATION_EXISTS" in result.output

    def test_fork_invalid_name_short_circuits(self) -> None:
        runner = CliRunner()
        with patch(
            "convilyn_sdk._internal.templates.fork_template",
            side_effect=TemplateError("bad name", code="INVALID_NAME"),
        ):
            result = runner.invoke(cli, ["template", "fork", "blog", "Bad Name"])
        assert result.exit_code == 1
        assert "INVALID_NAME" in result.output
