"""Tests for the document-analyzer workflow example."""

import pytest
from server import server
from workflow import workflow

from convilyn_sdk.testing import ConvilynTestRunner, WorkflowTestRunner


@pytest.fixture
def tool_runner():
    return ConvilynTestRunner(server=server)


@pytest.fixture
def workflow_runner():
    return WorkflowTestRunner(workflow=workflow, tool_servers=[server])


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


# ── Workflow Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_spec_valid(workflow_runner):
    result = await workflow_runner.validate_spec()
    assert result.valid, f"Spec errors: {result.errors}"


@pytest.mark.asyncio
async def test_workflow_tool_chain(workflow_runner):
    result = await workflow_runner.validate_tool_chain()
    assert result.valid, f"Tool chain errors: {result.errors}"


@pytest.mark.asyncio
async def test_workflow_dry_run(workflow_runner):
    result = await workflow_runner.run(mode="dry_run")
    assert result.passed, f"Dry run errors: {result.errors}"


@pytest.mark.asyncio
async def test_workflow_mock_run(workflow_runner):
    result = await workflow_runner.run(mode="mock")
    assert result.passed, f"Mock run errors: {result.errors}"
    assert len(result.tools_invoked) > 0, "No tools were invoked"
    assert len(result.phases_completed) > 0, "No phases completed"


@pytest.mark.asyncio
async def test_compiled_spec_structure(workflow_runner):
    """Verify the compiled spec has the expected top-level fields."""
    compiled = workflow_runner._compile()

    assert compiled["spec_id"] == "doc_analyzer"
    assert compiled["name"] == "Document Analyzer"
    assert compiled["version"] == "1.0.0"
    assert compiled["category"] == "goal_lane"
    assert "document" in compiled["supported_input_types"]
    assert compiled["mcp_config"]["mcp_servers"] == ["doc-analyzer"]
    assert len(compiled["mcp_config"]["tools"]) == 3
    assert len(compiled["phases"]) == 4
    assert compiled["agent_config"]["max_iterations"] == 20
    assert len(compiled["preflight_rules"]) == 1
    assert len(compiled["output_specs"]) == 1
