"""Tests for WorkflowTestRunner — tool chain validation and mock execution."""

import pytest

from convilyn_author import ToolServer, WorkflowSpec
from convilyn_author.testing.workflow_runner import WorkflowTestResult, WorkflowTestRunner


def _make_server():
    server = ToolServer(name="test-srv", description="T", version="0.1.0")

    @server.tool(description="Process text")
    async def process(text: str) -> dict:
        return {"ref_id": "td_abc", "summary": f"Processed {len(text)} chars"}

    @server.tool(description="Summarize text")
    async def summarize(text: str) -> dict:
        return {"summary": text[:20]}

    return server


def _make_workflow(server=None):
    server = server or _make_server()
    return (
        WorkflowSpec("test_wf", name="Test", version="1.0.0")
        .with_input(types=["document"], formats=["pdf"])
        .with_output(format="json")
        .from_server(server)
        .add_phase("Process", "Extract text using `test_srv__process`.")
        .add_phase("Summarize", "Summarize using `test_srv__summarize`.")
        .add_phase("Complete", "Call `complete_workflow`.")
        .with_agent_config(max_iterations=10)
        .add_preflight_rule("r", check_type="file_count", params={"min": 1}, error_message="E")
    )


# ── WorkflowTestResult ─────────────────────────────────────────


class TestWorkflowTestResult:
    def test_defaults(self):
        r = WorkflowTestResult()
        assert r.passed is True
        assert r.spec_valid is True
        assert r.tools_valid is True
        assert r.phases_completed == []
        assert r.tools_invoked == []
        assert r.errors == []
        assert r.execution_time_ms == 0.0


# ── Spec Validation ─────────────────────────────────────────────


class TestValidateSpec:
    @pytest.mark.asyncio
    async def test_valid_spec(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        result = await runner.validate_spec()
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_invalid_spec(self):
        bad_wf = WorkflowSpec("", name="")  # empty required fields
        runner = WorkflowTestRunner(bad_wf, [])
        result = await runner.validate_spec()
        assert result.valid is False


# ── Tool Chain Validation ───────────────────────────────────────


class TestValidateToolChain:
    @pytest.mark.asyncio
    async def test_all_tools_present(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        result = await runner.validate_tool_chain()
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_missing_tools(self):
        server = _make_server()
        workflow = (
            WorkflowSpec("x", name="X")
            .use_tools("missing-srv:missing_tool")
            .use_servers("missing-srv")
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.validate_tool_chain()
        assert result.valid is False


# ── Dry Run ─────────────────────────────────────────────────────


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_passes_for_valid(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        result = await runner.run(mode="dry_run")
        assert result.passed is True
        assert result.tools_invoked == []
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_dry_run_fails_for_invalid_spec(self):
        bad_wf = WorkflowSpec("", name="")
        runner = WorkflowTestRunner(bad_wf, [])
        result = await runner.run(mode="dry_run")
        assert result.passed is False
        assert result.spec_valid is False

    @pytest.mark.asyncio
    async def test_dry_run_fails_for_missing_tools(self):
        server = _make_server()
        workflow = (
            WorkflowSpec("test.dry_run", name="DryRun", version="1.0.0")
            .use_tools("missing:tool")
            .use_servers("missing")
            .add_phase("P", "D")
            .with_output(format="txt")
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.run(mode="dry_run")
        assert result.passed is False
        assert result.tools_valid is False


# ── Mock Run ────────────────────────────────────────────────────


class TestMockRun:
    @pytest.mark.asyncio
    async def test_mock_run_invokes_tools(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        result = await runner.run(mode="mock")
        assert result.passed is True
        assert len(result.tools_invoked) > 0
        assert len(result.phases_completed) == 3
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_mock_run_captures_outputs(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        result = await runner.run(mode="mock")
        assert len(result.outputs) > 0

    @pytest.mark.asyncio
    async def test_mock_run_no_phases_invokes_all_tools(self):
        """When no tools mentioned in phases, fallback to invoking all tools."""
        server = _make_server()
        workflow = (
            WorkflowSpec("test.fallback", name="Fallback", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "Do things without backtick references.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.run(mode="mock")
        assert result.passed is True
        assert len(result.tools_invoked) == 2  # all tools invoked

    @pytest.mark.asyncio
    async def test_mock_run_with_tool_error(self):
        server = ToolServer(name="err-srv", description="T", version="0.1.0")

        @server.tool(description="Failing tool")
        async def fail_tool(text: str) -> dict:
            raise ValueError("Tool broken")

        workflow = (
            WorkflowSpec("test.err_wf", name="Error WF", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "Use `err_srv__fail_tool`.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.run(mode="mock")
        assert result.passed is False
        assert any("Tool broken" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_mock_run_missing_server_fails_coverage(self):
        """Tools from missing servers cause tool_coverage validation to fail."""
        server = _make_server()
        workflow = (
            WorkflowSpec("test.skip_srv", name="Skip", version="1.0.0")
            .with_output(format="txt")
            .use_tools("test-srv:process", "other-srv:other_tool")
            .use_servers("test-srv", "other-srv")
            .add_phase("P", "Use `test_srv__process`.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.run(mode="mock")
        # Missing server tool fails tool coverage validation
        assert result.passed is False
        assert result.tools_valid is False

    @pytest.mark.asyncio
    async def test_mock_run_tool_not_registered_on_server(self):
        server = _make_server()
        workflow = (
            WorkflowSpec("test.noreg", name="NoReg", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "Use `test_srv__nonexistent`.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])
        # nonexistent won't match any tool_ref, so no invocation from phase
        # fallback invokes all tools
        result = await runner.run(mode="mock")
        assert result.passed is True


# ── Edge Cases for full coverage ─────────────────────────────────


class TestMockRunEdgeCases:
    """Test edge cases by providing matching servers for coverage validation,
    but exercising specific branches during mock execution."""

    @pytest.mark.asyncio
    async def test_phase_mentions_tool_on_absent_server_in_map(self):
        """Phase references a tool whose server has no match in server_map.

        We provide both servers for coverage validation, but only pass one
        to the runner for execution, testing the 'server not in map' branch.
        """
        server = _make_server()
        absent_srv = ToolServer(name="absent-srv", description="T", version="0.1.0")

        @absent_srv.tool(description="T")
        async def some_tool(text: str = "x") -> dict:
            return {"ok": True}

        workflow = (
            WorkflowSpec("test.miss_phase", name="Miss", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .from_server(absent_srv)
            .add_phase("P", "Use `absent_srv__some_tool` and `test_srv__process`.")
            .with_agent_config(max_iterations=10)
        )
        # Pass both for coverage validation, but internally the runner uses
        # server_map; absent_srv IS present so all tools should work
        runner = WorkflowTestRunner(workflow, [server, absent_srv])
        result = await runner.run(mode="mock")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_phase_server_not_in_map(self):
        """Phase mentions tool from a server not in the runner's server list."""
        server = _make_server()
        workflow = (
            WorkflowSpec("test.no_map", name="NoMap", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "Use `absent_srv__some_tool`.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])

        # Patch compiled spec to add absent server tool in mcp_config.tools
        import copy

        compiled = copy.deepcopy(runner._compile())
        compiled["mcp_config"]["tools"].append("absent-srv:some_tool")
        compiled["mcp_config"]["mcp_servers"].append("absent-srv")
        runner._compiled = compiled

        # Bypass validation
        from convilyn_author.testing import workflow_runner as wr_module
        from convilyn_author.workflow_validator import WorkflowValidationResult

        orig_vws = wr_module.validate_workflow_spec
        orig_vtc = wr_module.validate_tool_coverage
        wr_module.validate_workflow_spec = lambda s: WorkflowValidationResult()
        wr_module.validate_tool_coverage = lambda s, servers: WorkflowValidationResult()
        try:
            result = await runner.run(mode="mock")
        finally:
            wr_module.validate_workflow_spec = orig_vws
            wr_module.validate_tool_coverage = orig_vtc

        # absent-srv is skipped (not in server_map), test-srv tools work
        assert any("test-srv:" in t for t in result.tools_invoked)

    @pytest.mark.asyncio
    async def test_phase_tool_not_on_server(self):
        """Phase references tool not registered — get_tool returns None."""
        server = _make_server()
        workflow = (
            WorkflowSpec("test.unreg", name="Unreg", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "Use `test_srv__process`.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])

        # Monkey-patch get_tool to return None (simulating tool not found)
        original_get_tool = server.get_tool
        server.get_tool = lambda name: None

        # Also bypass validation since it passes normally
        from convilyn_author.testing import workflow_runner as wr_module
        from convilyn_author.workflow_validator import WorkflowValidationResult

        orig_vws = wr_module.validate_workflow_spec
        orig_vtc = wr_module.validate_tool_coverage
        wr_module.validate_workflow_spec = lambda s: WorkflowValidationResult()
        wr_module.validate_tool_coverage = lambda s, servers: WorkflowValidationResult()

        try:
            result = await runner.run(mode="mock")
        finally:
            server.get_tool = original_get_tool
            wr_module.validate_workflow_spec = orig_vws
            wr_module.validate_tool_coverage = orig_vtc

        assert any("not found on server" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_fallback_edge_cases_via_patched_spec(self):
        """Test fallback path edge cases by patching compiled spec after validation.

        Covers: malformed tool ref (no colon), absent server, unregistered tool.
        """
        import copy

        server = _make_server()
        workflow = (
            WorkflowSpec("test.fb_edge", name="FBEdge", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "No backtick refs at all here.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])

        # First compile (valid), then patch the cached spec
        compiled = copy.deepcopy(runner._compile())
        compiled["mcp_config"]["tools"] = [
            "no_colon",  # malformed → skip (L180)
            "absent-srv:tool",  # server not in map → skip (L184)
            "test-srv:ghost",  # tool not found → skip (L189)
            "test-srv:process",  # success
        ]
        compiled["mcp_config"]["mcp_servers"] = ["test-srv", "absent-srv"]
        runner._compiled = compiled

        # Monkey-patch validate_workflow_spec and validate_tool_coverage to pass
        from convilyn_author.testing import workflow_runner as wr_module

        orig_vws = wr_module.validate_workflow_spec
        orig_vtc = wr_module.validate_tool_coverage

        from convilyn_author.workflow_validator import WorkflowValidationResult

        wr_module.validate_workflow_spec = lambda s: WorkflowValidationResult()
        wr_module.validate_tool_coverage = lambda s, servers: WorkflowValidationResult()
        try:
            result = await runner.run(mode="mock")
        finally:
            wr_module.validate_workflow_spec = orig_vws
            wr_module.validate_tool_coverage = orig_vtc

        assert "test-srv:process" in result.tools_invoked
        assert "no_colon" not in result.tools_invoked
        assert "absent-srv:tool" not in result.tools_invoked
        assert "test-srv:ghost" not in result.tools_invoked

    @pytest.mark.asyncio
    async def test_fallback_tool_error(self):
        """Fallback invocation captures tool errors."""
        server = ToolServer(name="fail-srv", description="T", version="0.1.0")

        @server.tool(description="Fails")
        async def broken(text: str) -> dict:
            raise RuntimeError("Broken in fallback")

        workflow = (
            WorkflowSpec("test.fb_err", name="FBErr", version="1.0.0")
            .with_output(format="txt")
            .from_server(server)
            .add_phase("P", "No matching backtick refs here.")
            .with_agent_config(max_iterations=10)
        )
        runner = WorkflowTestRunner(workflow, [server])
        result = await runner.run(mode="mock")
        assert result.passed is False
        assert any("Broken in fallback" in e for e in result.errors)


# ── Extract Tool Mentions ───────────────────────────────────────


class TestExtractToolMentions:
    def test_backtick_pattern(self):
        refs = ["test-srv:process", "test-srv:summarize"]
        mentions = WorkflowTestRunner._extract_tool_mentions(
            "Use `test_srv__process` to extract.", refs
        )
        assert "test-srv:process" in mentions

    def test_tool_name_only(self):
        refs = ["test-srv:process"]
        mentions = WorkflowTestRunner._extract_tool_mentions("Use `process` to extract.", refs)
        assert "test-srv:process" in mentions

    def test_no_matches(self):
        refs = ["test-srv:process"]
        mentions = WorkflowTestRunner._extract_tool_mentions("No backtick references here.", refs)
        assert mentions == []

    def test_no_duplicates(self):
        refs = ["test-srv:process"]
        mentions = WorkflowTestRunner._extract_tool_mentions(
            "Use `test_srv__process` twice: `test_srv__process`.", refs
        )
        assert len(mentions) == 1

    def test_multiple_tools(self):
        refs = ["srv:t1", "srv:t2"]
        mentions = WorkflowTestRunner._extract_tool_mentions("Use `srv__t1` then `srv__t2`.", refs)
        assert len(mentions) == 2


# ── Compile Caching ─────────────────────────────────────────────


class TestCompileCaching:
    def test_compile_cached(self):
        server = _make_server()
        runner = WorkflowTestRunner(_make_workflow(server), [server])
        c1 = runner._compile()
        c2 = runner._compile()
        assert c1 is c2  # same object
