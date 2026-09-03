"""Tests for the document-analyzer tool-server example."""

import pytest
from server import server

from convilyn_author.testing import ConvilynTestRunner


@pytest.fixture
def tool_runner():
    return ConvilynTestRunner(server=server)


# ── Tool Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_text(tool_runner):
    result = await tool_runner.call_tool(
        "extract_text", {"content": "Hello world. This is a test document.", "file_type": "txt"}
    )
    assert result.success
    assert "ref_id" in result.data
    assert "summary" in result.data


@pytest.mark.asyncio
async def test_analyze_text(tool_runner):
    result = await tool_runner.call_tool(
        "analyze_text", {"text": "Python programming language is great for data analysis"}
    )
    assert result.success
    assert "ref_id" in result.data


@pytest.mark.asyncio
async def test_summarize(tool_runner):
    result = await tool_runner.call_tool(
        "summarize",
        {"text": "This is a long document. It has many sentences. The topic is important."},
    )
    assert result.success
    assert "summary" in result.data


@pytest.mark.asyncio
async def test_compliance(tool_runner):
    report = await tool_runner.run_compliance_check()
    assert report.all_passed, f"Failed checks: {report.failed}"
