"""Tests for the weather server example."""

import pytest
from server import server

from convilyn_author.testing import ConvilynTestRunner, assert_schema_valid, assert_tool_success


@pytest.fixture
def runner():
    return ConvilynTestRunner(server=server)


@pytest.mark.asyncio
async def test_get_weather(runner):
    result = await runner.call_tool("get_weather", {"location": "Tokyo"})
    assert_tool_success(result)
    assert_schema_valid(result.data, ["ref_id", "summary"])


@pytest.mark.asyncio
async def test_get_forecast(runner):
    result = await runner.call_tool("get_forecast", {"location": "London", "days": 3})
    assert_tool_success(result)
    assert_schema_valid(result.data, ["ref_id", "summary"])


@pytest.mark.asyncio
async def test_compliance(runner):
    report = await runner.run_compliance_check()
    assert report.all_passed, f"Failed: {[r.message for r in report.failed]}"


def test_manifest_synth():
    manifest = server.synth()
    assert manifest.server.name == "weather-data"
    assert len(manifest.tools) == 2
    assert "weather" in manifest.capabilities
