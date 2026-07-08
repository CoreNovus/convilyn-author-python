"""Pre-submission validation for workflow specifications.

Validates compiled workflow specs before pushing to the platform,
catching common errors early without requiring a network round-trip.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from convilyn_sdk.server import ToolServer


class WorkflowValidationResult(BaseModel):
    """Result of workflow spec validation."""

    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_SPEC_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.]+$")
_TOOL_REF_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+:[a-zA-Z0-9_.]+$")


def validate_workflow_spec(spec: dict[str, Any]) -> WorkflowValidationResult:
    """Validate a compiled workflow spec dict.

    Checks:
        1. Required fields present (spec_id, name, version)
        2. Version is valid semver
        3. spec_id follows naming convention
        4. MCP tool references are syntactically valid
        5. Phase descriptions are non-empty
        6. Agent config bounds (temperature, iterations)
        7. Slot IDs are unique
        8. Preflight rule IDs are unique
        9. At least one output spec exists
        10. MCP servers referenced by tools are listed
    """
    result = WorkflowValidationResult()

    # 1. Required fields
    for field in ("spec_id", "name", "version"):
        if not spec.get(field):
            result.add_error(f"Missing required field: {field}")

    if not result.valid:
        return result

    spec_id = spec["spec_id"]
    version = spec["version"]

    # 2. Semver
    if not _SEMVER_PATTERN.match(version):
        result.add_error(f"Version must be semver (x.y.z), got: {version}")

    # 3. spec_id naming
    if not _SPEC_ID_PATTERN.match(spec_id):
        result.add_error(
            f"spec_id must be alphanumeric with dots/underscores, got: {spec_id}"
        )

    # 4. MCP tool references
    mcp_config = spec.get("mcp_config")
    if mcp_config:
        tools = mcp_config.get("tools", [])
        servers_from_tools: set[str] = set()

        for tool_ref in tools:
            if not _TOOL_REF_PATTERN.match(tool_ref):
                result.add_error(
                    f'Invalid tool reference: {tool_ref!r}. Must be "server:tool" format.'
                )
            else:
                server_name = tool_ref.split(":")[0]
                servers_from_tools.add(server_name)

        # 10. Servers referenced by tools are listed in mcp_servers
        listed_servers = set(mcp_config.get("mcp_servers", []))
        missing_servers = servers_from_tools - listed_servers
        if missing_servers:
            result.add_error(
                f"Tools reference servers not listed in mcp_servers: {sorted(missing_servers)}"
            )

        if not tools:
            result.add_warning("No tools defined in mcp_config")

    # 5. Phase descriptions
    phases = spec.get("phases", [])
    for i, phase in enumerate(phases):
        if not phase.get("phase"):
            result.add_error(f"Phase {i} missing 'phase' (name)")
        if not phase.get("description"):
            result.add_error(f"Phase {i} ({phase.get('phase', '?')}) has empty description")

    if not phases:
        result.add_warning("No phases defined — agent will rely solely on system prompt")

    # 6. Agent config bounds
    agent_config = spec.get("agent_config")
    if agent_config:
        temp = agent_config.get("temperature", 0.3)
        if not (0.0 <= temp <= 1.0):
            result.add_error(f"Agent temperature must be 0.0–1.0, got: {temp}")

        max_iter = agent_config.get("max_iterations", 25)
        if not (1 <= max_iter <= 50):
            result.add_error(f"Agent max_iterations must be 1–50, got: {max_iter}")

    # 7. Unique slot IDs
    seen_slot_ids: set[str] = set()
    for slot_list in (spec.get("required_slots", []), spec.get("optional_slots", [])):
        for slot in slot_list:
            sid = slot.get("slot_id", "")
            if sid in seen_slot_ids:
                result.add_error(f"Duplicate slot_id: {sid}")
            seen_slot_ids.add(sid)

    # 8. Unique preflight rule IDs
    seen_rule_ids: set[str] = set()
    for rule in spec.get("preflight_rules", []):
        rid = rule.get("rule_id", "")
        if rid in seen_rule_ids:
            result.add_error(f"Duplicate preflight rule_id: {rid}")
        seen_rule_ids.add(rid)

    # 9. At least one output
    if not spec.get("output_specs"):
        result.add_warning("No output_specs defined — workflow produces no downloadable files")

    # 11. Multi-role block — cheap structural checks so authors catch
    # typos before submit. The full per-field validation runs on the
    # platform at spec load.
    multi_agent = spec.get("multi_agent")
    if multi_agent:
        active = multi_agent.get("active_specialists", [])
        if not active:
            result.add_error("multi_agent.active_specialists must not be empty")
        if len(active) != len(set(active)):
            result.add_error(
                "multi_agent.active_specialists contains duplicates "
                "(the platform will reject at spec load)"
            )
        specialists_map = multi_agent.get("specialists") or {}
        stray_keys = set(specialists_map.keys()) - set(active)
        if stray_keys:
            result.add_error(
                "multi_agent.specialists declares roles not in "
                f"active_specialists: {sorted(stray_keys)}"
            )

    # 12. Resume boundaries — phase references should resolve. A
    # warning, not an error: the platform may inject phases at runtime
    # (e.g. cross-spec composition) so a stale-but-known phase name
    # shouldn't block submission.
    checkpoints = spec.get("checkpoints") or {}
    known_phase_names = {p.get("phase") for p in spec.get("phases", []) if p.get("phase")}
    for cp_id, cp in checkpoints.items():
        after_phase = cp.get("after_phase")
        if not after_phase:
            result.add_error(f"checkpoint {cp_id!r} missing required 'after_phase'")
            continue
        if known_phase_names and after_phase not in known_phase_names:
            result.add_warning(
                f"checkpoint {cp_id!r} references unknown phase "
                f"{after_phase!r}; declared phases are {sorted(known_phase_names)}"
            )
        if not cp.get("slots"):
            result.add_error(f"checkpoint {cp_id!r} must declare at least one slot")

    # 13. Routing — surface the platform's max_steps advisory locally.
    routing = spec.get("routing")
    if routing:
        max_steps = routing.get("max_steps")
        if max_steps is not None:
            if not isinstance(max_steps, int) or max_steps < 1 or max_steps > 200:
                result.add_error(
                    f"routing.max_steps must be 1-200, got: {max_steps}"
                )
            elif max_steps > 100:
                result.add_warning(
                    f"routing.max_steps={max_steps} exceeds the 100-step advisory "
                    "threshold; verify estimated_cost_u is calibrated."
                )

    return result


def validate_tool_coverage(
    spec: dict[str, Any],
    tool_servers: list[ToolServer],
) -> WorkflowValidationResult:
    """Verify all tools referenced in mcp_config exist in provided ToolServer(s).

    Args:
        spec: Compiled workflow spec dict.
        tool_servers: List of ToolServer instances to check against.

    Returns:
        Validation result with errors for missing tools.
    """
    result = WorkflowValidationResult()

    mcp_config = spec.get("mcp_config")
    if not mcp_config:
        result.add_warning("No mcp_config in spec — nothing to validate")
        return result

    # Build available tool map: "server:tool" → True
    available: set[str] = set()
    for server in tool_servers:
        for tool_name in server.tool_names:
            available.add(f"{server.name}:{tool_name}")

    # Check each referenced tool
    for tool_ref in mcp_config.get("tools", []):
        if tool_ref not in available:
            result.add_error(
                f"Tool {tool_ref!r} not found in provided servers. "
                f"Available: {sorted(available)}"
            )

    # Check server names
    available_servers = {s.name for s in tool_servers}
    for server_name in mcp_config.get("mcp_servers", []):
        if server_name not in available_servers:
            result.add_warning(
                f"Server {server_name!r} not in provided tool_servers "
                f"(may be a platform-provided server)"
            )

    return result
