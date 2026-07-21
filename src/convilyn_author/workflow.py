"""WorkflowSpec — fluent builder for Convilyn workflow definitions.

Developers use this builder to define workflow specifications that
compile to the platform's wire JSON. Every mutation method returns a
new WorkflowSpec instance (immutability).

Usage::

    from convilyn_author import ToolServer, WorkflowSpec

    server = ToolServer(name="my-analyzer", description="Text analysis tools")

    @server.tool(description="Analyze text")
    async def analyze_text(text: str) -> dict: ...

    workflow = (
        WorkflowSpec("my_text_analyzer", name="Text Analyzer")
        .with_input(types=["document"], formats=["pdf", "txt"])
        .with_output(format="json", additional={"type": "analysis_result"})
        .from_server(server)
        .add_phase("Parse", "Extract text using `my_analyzer__analyze_text`.")
        .with_agent_config(max_iterations=20, temperature=0.3)
    )

    spec_json = workflow.compile()
    workflow.save("workflow.spec.json")
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from convilyn_author.workflow_advanced_types import (
    AutonomyLevel,
    CheckpointConfig,
    MultiRoleConfig,
    RoleConfig,
)
from convilyn_author.workflow_policies import (
    ClarifyCondition,
    FallbackPolicyConfig,
    InferCondition,
    QaPolicyConfig,
    RetryPolicyConfig,
    RoutingPolicyConfig,
    StopCondition,
    TaskPolicyConfig,
    _coerce_to_model,
)
from convilyn_author.workflow_types import (
    AgentConfigModel,
    InputConfig,
    LocalePolicyConfig,
    MCPConfigModel,
    OutputSpecConfig,
    PhaseConfig,
    PreflightRuleConfig,
    SlotConfig,
    WorkflowBlueprint,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from convilyn_author._internal.policy_protocol import PolicyProtocol
    from convilyn_author.agent_role import AgentRole
    from convilyn_author.server import ToolServer


class WorkflowSpec:
    """Fluent builder for defining Convilyn workflow specifications.

    Every method returns a **new** WorkflowSpec — the original is never
    mutated. Call ``compile()`` to produce a dict ready for the platform.
    """

    def __init__(
        self,
        spec_id: str,
        *,
        name: str,
        version: str = "1.0.0",
        description: str | None = None,
        category: str = "goal_lane",
        platform: str = "multi",
    ) -> None:
        self._spec_id = spec_id
        self._name = name
        self._version = version
        self._description = description
        self._category = category
        self._platform = platform
        self._description_i18n: dict[str, str] | None = None
        self._aliases: list[str] = []
        self._keywords: list[str] = []
        # Pydantic v2 generates __init__ with all-default kwargs; pyright
        # can't see that statically. The no-arg call is correct at runtime.
        self._input = InputConfig()  # pyright: ignore[reportCallIssue]
        self._outputs: list[OutputSpecConfig] = []
        self._mcp_config = MCPConfigModel()
        self._agent_config: AgentConfigModel | None = None
        self._phases: list[PhaseConfig] = []
        self._required_slots: list[SlotConfig] = []
        self._optional_slots: list[SlotConfig] = []
        self._preflight_rules: list[PreflightRuleConfig] = []
        self._locale_policy = LocalePolicyConfig()  # pyright: ignore[reportCallIssue]
        self._multi_agent: MultiRoleConfig | None = None
        self._checkpoints: dict[str, CheckpointConfig] = {}
        self._task_policy: TaskPolicyConfig | None = None
        self._routing: RoutingPolicyConfig | None = None
        self._qa_policy: QaPolicyConfig | None = None

    # ── Private clone helper ──────────────────────────────────────

    def _clone(self) -> WorkflowSpec:
        """Create a deep copy of this spec."""
        new = WorkflowSpec.__new__(WorkflowSpec)
        for attr in vars(self):
            setattr(new, attr, copy.deepcopy(getattr(self, attr)))
        return new

    # ── Identity & Metadata ───────────────────────────────────────

    def with_description(self, description: str) -> WorkflowSpec:
        """Set the workflow description."""
        clone = self._clone()
        clone._description = description
        return clone

    def with_description_i18n(self, translations: dict[str, str]) -> WorkflowSpec:
        """Set locale-keyed descriptions (e.g. {"en": "...", "zh": "..."})."""
        clone = self._clone()
        clone._description_i18n = dict(translations)
        return clone

    def with_aliases(self, *aliases: str) -> WorkflowSpec:
        """Set alternative names for NLP matching."""
        clone = self._clone()
        clone._aliases = list(aliases)
        return clone

    def with_keywords(self, *keywords: str) -> WorkflowSpec:
        """Set keywords for NLP matching."""
        clone = self._clone()
        clone._keywords = list(keywords)
        return clone

    # ── Input Configuration ───────────────────────────────────────

    def with_input(
        self,
        types: list[str],
        formats: list[str] | None = None,
        max_size_bytes: int = 10_485_760,
        max_duration_seconds: int | None = None,
        min_duration_seconds: int | None = None,
        min_file_count: int | None = None,
    ) -> WorkflowSpec:
        """Configure input constraints."""
        clone = self._clone()
        clone._input = InputConfig(
            types=list(types),
            formats=list(formats) if formats else None,
            max_size_bytes=max_size_bytes,
            max_duration_seconds=max_duration_seconds,
            min_duration_seconds=min_duration_seconds,
            min_file_count=min_file_count,
        )
        return clone

    # ── Output Configuration ──────────────────────────────────────

    def with_output(self, format: str, **additional: Any) -> WorkflowSpec:
        """Add an output spec. Chainable — each call adds one output."""
        clone = self._clone()
        clone._outputs = [*clone._outputs, OutputSpecConfig(format=format, additional=additional)]
        return clone

    # ── MCP Tool Composition ──────────────────────────────────────

    def use_tools(self, *tool_refs: str) -> WorkflowSpec:
        """Add MCP tool references in "server:tool" format."""
        clone = self._clone()
        existing = set(clone._mcp_config.tools)
        new_tools = [ref for ref in tool_refs if ref not in existing]
        clone._mcp_config = MCPConfigModel(
            mcp_servers=list(clone._mcp_config.mcp_servers),
            tools=[*clone._mcp_config.tools, *new_tools],
        )
        return clone

    def use_servers(self, *server_names: str) -> WorkflowSpec:
        """Add MCP server names."""
        clone = self._clone()
        existing = set(clone._mcp_config.mcp_servers)
        new_servers = [s for s in server_names if s not in existing]
        clone._mcp_config = MCPConfigModel(
            mcp_servers=[*clone._mcp_config.mcp_servers, *new_servers],
            tools=list(clone._mcp_config.tools),
        )
        return clone

    def from_server(self, server: ToolServer) -> WorkflowSpec:
        """Auto-populate mcp_config from a ToolServer instance.

        Adds the server name and all its tools in "server:tool" format.
        """
        tool_refs = [f"{server.name}:{name}" for name in server.tool_names]
        return self.use_servers(server.name).use_tools(*tool_refs)

    # ── Agent Configuration ───────────────────────────────────────

    def with_agent_config(
        self,
        *,
        system_prompt: str | None = None,
        max_iterations: int = 25,
        temperature: float = 0.3,
    ) -> WorkflowSpec:
        """Configure agent-mode knobs.

        Public knobs only: an optional author-supplied ``system_prompt``
        text, the iteration cap, and temperature. Prompt-template selection
        and engine-tuning internals are owned by the platform and chosen
        server-side — they are not part of the public blueprint.

        An ``allow_dynamic_slots`` opt-in set via :meth:`with_dynamic_slots`
        is PRESERVED across this call, so the two builders compose in any
        order (this method rebuilds the ``agent_config`` block but does not
        silently drop a dynamic-slots opt-in).
        """
        clone = self._clone()
        # Preserve an already-set dynamic-slots opt-in (from
        # ``with_dynamic_slots``) — this method rebuilds the whole
        # agent_config block, so without this the flag would be wiped
        # depending on call order. Keeping it is the least-surprising
        # behaviour: the author explicitly opted in.
        allow_dynamic_slots = (
            clone._agent_config.allow_dynamic_slots if clone._agent_config is not None else None
        )
        clone._agent_config = AgentConfigModel(
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            temperature=temperature,
            allow_dynamic_slots=allow_dynamic_slots,
        )
        return clone

    def with_dynamic_slots(self, enabled: bool = True) -> WorkflowSpec:
        """Opt this workflow into runtime **dynamic slots** (issue 2435).

        By default a compiled workflow enforces a no-runtime-HITL contract:
        the only user inputs the platform may request are the ones the
        author statically pre-enumerates (``add_slot`` /
        ``with_resume_boundary``). Calling this with ``enabled=True`` sets
        ``agent_config.allow_dynamic_slots = True`` on the compiled
        blueprint, telling the platform it MAY additionally issue slots it
        computes at execution time — e.g. a missing companion file it only
        discovers it needs once the run is under way — rather than being
        limited to the pre-declared slot set.

        Round-trip: when the platform issues a dynamic slot, the consumer
        SDK's ``wait()`` surfaces it via ``slots_pending`` exactly as it
        already does for static slots — no consumer-side change is needed;
        the author opt-in is the only new surface.

        Default OFF and additive: an un-opted-in workflow serializes
        byte-identically to before (no ``allow_dynamic_slots`` key). Like
        every builder method this returns a NEW ``WorkflowSpec`` — the
        original is untouched. Composes with :meth:`with_agent_config` in
        any order; pass ``enabled=False`` to explicitly turn a prior opt-in
        back off (emits nothing, i.e. off).
        """
        clone = self._clone()
        base = clone._agent_config if clone._agent_config is not None else AgentConfigModel()
        # ``True`` opts in; ``None`` (not ``False``) turns it off so the key
        # is omitted under ``exclude_none`` — matching the default-off wire
        # shape rather than emitting an explicit ``false``.
        clone._agent_config = base.model_copy(
            update={"allow_dynamic_slots": True if enabled else None}
        )
        return clone

    # ── Phases ────────────────────────────────────────────────────

    def add_phase(self, name: str, description: str) -> WorkflowSpec:
        """Add a workflow phase (agent instruction block)."""
        clone = self._clone()
        clone._phases = [*clone._phases, PhaseConfig(phase=name, description=description)]
        return clone

    # ── Slots ─────────────────────────────────────────────────────

    def add_slot(
        self,
        slot_id: str,
        type: str,
        question: str,
        *,
        required: bool = False,
        **kwargs: Any,
    ) -> WorkflowSpec:
        """Add a user input slot.

        Args:
            slot_id: Unique identifier for the slot.
            type: Slot type (choice, multi_choice, text, number, boolean, file, date).
            question: Question displayed to user.
            required: Whether the slot is required.
            **kwargs: Additional SlotConfig fields (options, default, hidden, etc.).
        """
        clone = self._clone()
        # ``type`` is a runtime-validated string against the SlotConfig
        # Literal whitelist; Pydantic raises ValidationError on bad
        # values, so the runtime contract is preserved even though the
        # static checker can't narrow str → Literal at this boundary.
        slot = SlotConfig(
            slot_id=slot_id,
            type=type,  # pyright: ignore[reportArgumentType]
            question=question,
            required=required,
            **kwargs,
        )
        if required:
            clone._required_slots = [*clone._required_slots, slot]
        else:
            clone._optional_slots = [*clone._optional_slots, slot]
        return clone

    # ── Preflight Rules ───────────────────────────────────────────

    def add_preflight_rule(
        self,
        rule_id: str,
        *,
        check_type: str,
        params: dict[str, Any],
        error_message: str,
        description: str = "",
        is_blocking: bool = True,
    ) -> WorkflowSpec:
        """Add a preflight validation rule."""
        clone = self._clone()
        rule = PreflightRuleConfig(
            rule_id=rule_id,
            description=description,
            check_type=check_type,
            params=params,
            error_message=error_message,
            is_blocking=is_blocking,
        )
        clone._preflight_rules = [*clone._preflight_rules, rule]
        return clone

    # ── Locale Policy ─────────────────────────────────────────────

    def with_locale_policy(
        self,
        type: str = "locale_independent",
        *,
        locale_market_map: dict[str, str] | None = None,
        affected_slots: list[str] | None = None,
        prompt_hint: str | None = None,
    ) -> WorkflowSpec:
        """Configure locale behavior policy."""
        clone = self._clone()
        # Pydantic v2 narrows ``str`` → Literal at runtime; static
        # checkers can't narrow at the boundary so the ignore is
        # targeted to the one keyword arg.
        clone._locale_policy = LocalePolicyConfig(
            type=type,  # pyright: ignore[reportArgumentType]
            locale_market_map=locale_market_map,
            affected_slots=affected_slots or [],
            prompt_hint=prompt_hint,
        )
        return clone

    # ── Multi-role ────────────────────────────────────────────────

    def with_multi_role(
        self,
        *,
        active_specialists: Sequence[str | AgentRole],
        specialists: Mapping[str, RoleConfig | Mapping[str, Any]] | None = None,
        workflow_context: Mapping[str, Any] | None = None,
        rule_bundle_ref: str | None = None,
        rule_bundle_version: str | None = None,
        autonomy_level: AutonomyLevel = "require_verification",
        max_total_tool_calls: int = 100,
        max_role_visits: int = 3,
    ) -> WorkflowSpec:
        """Opt this workflow into multi-role execution.

        Accepts EITHER bare role strings OR objects satisfying the
        :class:`~convilyn_author.agent_role.AgentRole` Protocol (anything
        with a ``role`` attribute and an optional ``tool_allowlist``).
        AgentRole objects with a ``tool_allowlist`` auto-populate the
        ``specialists={...}`` allowlist map — no need to repeat the
        allowlist when the author already encoded it on the object
        (this is the DIP payoff of the Protocol).

        Calling twice on the same builder REPLACES the previous block
        (no implicit merging — explicit composition is the author's
        job; matches the ``.with_agent_config`` convention).
        """
        clone = self._clone()
        roles, derived_specialists = _normalise_specialists(active_specialists)
        merged_specialists = _merge_specialist_configs(derived_specialists, specialists)
        clone._multi_agent = MultiRoleConfig(
            active_specialists=roles,
            specialists=merged_specialists or None,
            workflow_context=dict(workflow_context) if workflow_context else None,
            rule_bundle_ref=rule_bundle_ref,
            rule_bundle_version=rule_bundle_version,
            autonomy_level=autonomy_level,
            max_total_tool_calls=max_total_tool_calls,
            max_role_visits=max_role_visits,
        )
        return clone

    # ── Resume boundaries ─────────────────────────────────────────

    def with_resume_boundary(
        self,
        checkpoint_id: str,
        *,
        after_phase: str,
        reason: str,
        slots: Sequence[SlotConfig | Mapping[str, Any]],
    ) -> WorkflowSpec:
        """Add one mid-execution pause point.

        Additive — each call adds one entry to the ``checkpoints``
        dict; passing the same ``checkpoint_id`` twice REPLACES the
        prior entry (matches dict semantics and `.add_phase`'s
        last-write-wins behaviour for repeated names).

        ``slots`` accepts a sequence of either :class:`SlotConfig`
        instances or raw mappings (the SDK normalises mappings via
        ``SlotConfig.model_validate``). The list mirrors the same
        vocabulary the workflow uses for ``required_slots`` /
        ``optional_slots``, so the ``slot_needed`` event shape is
        unchanged whether the slot comes from a resume boundary or
        up-front user input.
        """
        clone = self._clone()
        normalised_slots = [
            slot if isinstance(slot, SlotConfig) else SlotConfig.model_validate(slot)
            for slot in slots
        ]
        clone._checkpoints = {
            **clone._checkpoints,
            checkpoint_id: CheckpointConfig(
                after_phase=after_phase,
                reason=reason,
                slots=normalised_slots,
            ),
        }
        return clone

    # ── High-level policies ───────────────────────────────────────

    def with_policy(self, *policies: PolicyProtocol) -> WorkflowSpec:
        """Apply one or more high-level policy knobs to this workflow.

        Accepts any object implementing :class:`PolicyProtocol` — the
        five built-in knobs (:class:`~convilyn_author.policies.RetryPolicy`,
        :class:`~convilyn_author.policies.TimeoutPolicy`, etc.) all conform.
        The SDK translates each knob into one or more wire blocks and
        merges them into the spec's compiled output. Two policies of
        the same kind, or two policies whose wire output collides on
        the same leaf, raise :class:`ValueError`.

        Combines with the granular ``with_task_policy`` /
        ``with_routing`` / ``with_qa_policy`` methods: their values
        compose as additional contributions to the same wire blocks.
        """
        from convilyn_author._internal.policy_translator import apply_policies

        clone = self._clone()
        base: dict[str, Any] = {}
        if clone._task_policy is not None:
            base["task_policy"] = clone._task_policy.model_dump(exclude_none=True)
        if clone._routing is not None:
            base["routing_policy"] = clone._routing.model_dump(exclude_none=True)
        if clone._qa_policy is not None:
            base["qa_policy"] = clone._qa_policy.model_dump(exclude_none=True)

        merged = apply_policies(policies, base)

        if "task_policy" in merged:
            clone._task_policy = TaskPolicyConfig.model_validate(merged["task_policy"])
        if "routing_policy" in merged:
            clone._routing = RoutingPolicyConfig.model_validate(merged["routing_policy"])
        if "qa_policy" in merged:
            clone._qa_policy = QaPolicyConfig.model_validate(merged["qa_policy"])
        return clone

    # ── Task Policy (granular) ────────────────────────────────────

    def with_task_policy(
        self,
        *,
        must_clarify_when: Sequence[ClarifyCondition] | None = None,
        may_infer_when: Sequence[InferCondition] | None = None,
        must_stop_when: Sequence[StopCondition] | None = None,
    ) -> WorkflowSpec:
        """Declare when the agent must clarify / may infer / must stop.

        All three lists default to empty (permissive). Calling twice
        REPLACES the block — explicit composition is the author's job.
        ``ClarifyCondition`` / ``InferCondition`` / ``StopCondition``
        are bounded vocabularies; the IDE auto-completes the legal
        strings. For new code, prefer the high-level
        :class:`~convilyn_author.policies.FallbackPolicy` knob.
        """
        clone = self._clone()
        clone._task_policy = TaskPolicyConfig(
            must_clarify_when=list(must_clarify_when or []),
            may_infer_when=list(may_infer_when or []),
            must_stop_when=list(must_stop_when or []),
        )
        return clone

    # ── Routing Policy ────────────────────────────────────────────

    def with_routing(
        self,
        *,
        max_steps: int | None = None,
        retry_policy: RetryPolicyConfig | Mapping[str, Any] | None = None,
        fallback: FallbackPolicyConfig | Mapping[str, Any] | None = None,
    ) -> WorkflowSpec:
        """Configure the routing contract (max_steps + retry + fallback).

        ``max_steps`` is hard-capped at 200 by Pydantic; values above
        100 trigger a soft ``UserWarning`` at spec load. ``None``
        falls back to ``agent_config.max_iterations``.
        """
        clone = self._clone()
        clone._routing = RoutingPolicyConfig(
            max_steps=max_steps,
            retry_policy=_coerce_to_model(retry_policy, RetryPolicyConfig),
            fallback=_coerce_to_model(fallback, FallbackPolicyConfig),
        )
        return clone

    # ── QA Policy ─────────────────────────────────────────────────

    def with_qa_policy(
        self,
        *,
        slot_policy: Mapping[str, Any] | Any | None = None,
        goal_criteria: Mapping[str, Any] | Any | None = None,
        tool_pipeline: Sequence[Mapping[str, Any] | Any] | None = None,
        failure_rubric: Sequence[Mapping[str, Any] | Any] | None = None,
    ) -> WorkflowSpec:
        """Configure the QA policy (slot / goal / pipeline / rubric).

        Each sub-block is independently optional. Authors can pass
        either typed Pydantic config models or raw mappings — the SDK
        coerces mappings into the typed model so IDE autocompletion
        works on the way out (`compile()` returns dicts in either case).
        """
        from convilyn_author.workflow_policies import (
            FailureRuleConfig,
            GoalCriteriaConfig,
            SlotPolicyConfig,
            ToolStageConfig,
        )

        clone = self._clone()
        clone._qa_policy = QaPolicyConfig(
            slot_policy=_coerce_to_model(slot_policy, SlotPolicyConfig),
            goal_criteria=_coerce_to_model(goal_criteria, GoalCriteriaConfig),
            tool_pipeline=(
                [_coerce_to_model(stage, ToolStageConfig) for stage in tool_pipeline]
                if tool_pipeline is not None
                else None
            ),
            failure_rubric=(
                [_coerce_to_model(rule, FailureRuleConfig) for rule in failure_rubric]
                if failure_rubric is not None
                else None
            ),
        )
        return clone

    # ── Compile ───────────────────────────────────────────────────

    def compile(self) -> dict[str, Any]:
        """Compile this workflow into the public blueprint wire JSON.

        The output is a :class:`WorkflowBlueprint` — the public authoring
        shape. The platform translates it server-side into its executable
        form; platform-internal fields are not emitted here and are filled
        in during that translation.
        """
        spec = WorkflowBlueprint(
            spec_id=self._spec_id,
            version=self._version,
            name=self._name,
            description=self._description,
            description_i18n=self._description_i18n,
            aliases=self._aliases,
            keywords=self._keywords,
            supported_input_types=self._input.types,
            max_input_size_bytes=self._input.max_size_bytes,
            max_input_duration_seconds=self._input.max_duration_seconds,
            min_input_duration_seconds=self._input.min_duration_seconds,
            supported_input_formats=self._input.formats,
            output_specs=self._outputs,
            required_slots=self._required_slots,
            optional_slots=self._optional_slots,
            preflight_rules=self._preflight_rules,
            locale_policy=self._locale_policy,
            agent_config=self._agent_config,
            mcp_config=self._mcp_config if self._mcp_config.tools else None,
            phases=self._phases if self._phases else None,
            multi_agent=(
                self._multi_agent.model_dump(exclude_none=True)
                if self._multi_agent is not None
                else None
            ),
            checkpoints=(
                {cp_id: cp.model_dump(exclude_none=True) for cp_id, cp in self._checkpoints.items()}
                if self._checkpoints
                else None
            ),
            task_policy=(
                self._task_policy.model_dump(exclude_none=True)
                if self._task_policy is not None
                else None
            ),
            routing=(
                self._routing.model_dump(exclude_none=True) if self._routing is not None else None
            ),
            qa_policy=(
                self._qa_policy.model_dump(exclude_none=True)
                if self._qa_policy is not None
                else None
            ),
        )

        # Serialize with exclude_none so optional fields stay optional
        return spec.model_dump(exclude_none=True)

    # ── File I/O ──────────────────────────────────────────────────

    def save(self, path: str | Path = "workflow.spec.json") -> Path:
        """Compile and save the workflow spec to a JSON file."""
        compiled = self.compile()
        out_path = Path(path)
        out_path.write_text(
            json.dumps(compiled, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return out_path

    @classmethod
    def load(cls, path: str) -> WorkflowSpec:
        """Load a WorkflowSpec from a compiled JSON file.

        Reconstructs a WorkflowSpec builder from a previously compiled
        spec JSON. Useful for editing existing workflow definitions.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> WorkflowSpec:
        """Reconstruct a WorkflowSpec from a compiled dict.

        Internal factory: assigns fields directly on a fresh instance.
        This is an intentional exception to the immutable builder pattern
        — the instance is fully constructed before being returned.
        """
        spec = cls(
            spec_id=data["spec_id"],
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            category=data.get("category", "goal_lane"),
            platform=data.get("platform", "multi"),
        )

        spec._description_i18n = data.get("description_i18n")
        spec._aliases = data.get("aliases", [])
        spec._keywords = data.get("keywords", [])

        # Input — kwargs cover every InputConfig field, but pyright
        # sees a slimmer signature than Pydantic generates at runtime.
        spec._input = InputConfig(  # pyright: ignore[reportCallIssue]
            types=data.get("supported_input_types", []),
            formats=data.get("supported_input_formats"),
            max_size_bytes=data.get("max_input_size_bytes"),
            max_duration_seconds=data.get("max_input_duration_seconds"),
            min_duration_seconds=data.get("min_input_duration_seconds"),
        )

        # Outputs
        spec._outputs = [OutputSpecConfig(**o) for o in data.get("output_specs", [])]

        # MCP config
        mcp = data.get("mcp_config")
        if mcp:
            spec._mcp_config = MCPConfigModel(**mcp)

        # Agent config
        ac = data.get("agent_config")
        if ac:
            spec._agent_config = AgentConfigModel(**ac)

        # Phases
        phases = data.get("phases")
        if phases:
            spec._phases = [PhaseConfig(**p) for p in phases]

        # Slots
        spec._required_slots = [SlotConfig(**s) for s in data.get("required_slots", [])]
        spec._optional_slots = [SlotConfig(**s) for s in data.get("optional_slots", [])]

        # Preflight rules
        spec._preflight_rules = [PreflightRuleConfig(**r) for r in data.get("preflight_rules", [])]

        # Locale policy
        lp = data.get("locale_policy")
        if lp:
            spec._locale_policy = LocalePolicyConfig(**lp)

        # Advanced + policy blocks — round-trip via Pydantic so a loaded
        # spec is indistinguishable from one built fluently.
        ma = data.get("multi_agent")
        if ma:
            spec._multi_agent = MultiRoleConfig.model_validate(ma)

        cps = data.get("checkpoints")
        if cps:
            spec._checkpoints = {
                cp_id: CheckpointConfig.model_validate(cp_data) for cp_id, cp_data in cps.items()
            }

        tp = data.get("task_policy")
        if tp:
            spec._task_policy = TaskPolicyConfig.model_validate(tp)
        rt = data.get("routing")
        if rt:
            spec._routing = RoutingPolicyConfig.model_validate(rt)
        qa = data.get("qa_policy")
        if qa:
            spec._qa_policy = QaPolicyConfig.model_validate(qa)

        return spec

    # ── Representation ────────────────────────────────────────────

    def __repr__(self) -> str:
        tool_count = len(self._mcp_config.tools)
        phase_count = len(self._phases)
        return (
            f"WorkflowSpec(spec_id={self._spec_id!r}, name={self._name!r}, "
            f"version={self._version!r}, tools={tool_count}, phases={phase_count})"
        )


# ── Module-level helpers (DIP-aware role normalisation) ──────────────


def _normalise_specialists(
    active: Sequence[str | AgentRole],
) -> tuple[list[str], dict[str, RoleConfig]]:
    """Split a mixed ``str | AgentRole`` sequence into wire-shaped pieces.

    Returns:
        ``(role_strings, derived_roles)`` — ``role_strings`` is always
        a list of bare role names (the platform's wire shape for
        ``active_specialists``); ``derived_roles`` is the auto-populated
        allowlist map for any AgentRole instance whose ``tool_allowlist``
        is set.

    Duplicate role names raise ``ValueError`` — matches the platform's
    uniqueness check and catches the common authoring mistake (typoed
    role name re-added).
    """
    role_strings: list[str] = []
    derived: dict[str, RoleConfig] = {}
    seen: set[str] = set()
    for entry in active:
        if isinstance(entry, str):
            role = entry
        else:
            role = entry.role
            allowlist = entry.tool_allowlist
            if allowlist is not None:
                derived[role] = RoleConfig(tools=list(allowlist))
        if not role:
            raise ValueError("role cannot be empty")
        if role in seen:
            raise ValueError(f"duplicate role in active_specialists: {role!r}")
        seen.add(role)
        role_strings.append(role)
    return role_strings, derived


def _merge_specialist_configs(
    derived: dict[str, RoleConfig],
    explicit: Mapping[str, RoleConfig | Mapping[str, Any]] | None,
) -> dict[str, RoleConfig]:
    """Merge auto-derived + author-supplied role configs.

    Explicit author entries WIN over derivations from
    :class:`AgentRole` instances — the explicit map is the author's
    last word on the boundary. This matches the principle of least
    surprise: an author who passes ``specialists={"foo": {...}}``
    expects exactly that config to land on the wire, not a silent
    derivation overriding it.
    """
    merged = dict(derived)
    if explicit is None:
        return merged
    for role, value in explicit.items():
        merged[role] = value if isinstance(value, RoleConfig) else RoleConfig.model_validate(value)
    return merged
