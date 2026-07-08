"""Multi-role + resume-boundary demo workflow.

Exercises the fluent methods ``with_multi_role`` and
``with_resume_boundary`` so authors have a runnable reference for the
common pattern: declare two cooperating roles plus one mid-execution
pause for user disambiguation.

Run::

    python workflow.py            # writes finance_review.spec.json next to it
    python workflow.py --print    # also dumps the compiled JSON to stdout
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from convilyn_sdk import RoleConfig, WorkflowSpec
from convilyn_sdk.workflow_types import SlotConfig


@dataclass(frozen=True)
class AgentRole:
    """Authoring-time handle for a single role in a multi-role workflow.

    Conforms to :class:`convilyn_sdk.AgentRole` Protocol via duck
    typing — ``role`` (str) and ``tool_allowlist`` (list[str] | None).
    The SDK's ``with_multi_role`` auto-populates the per-role tool
    allowlist when the object supplies one (the DIP payoff).
    """

    role: str
    tool_allowlist: list[str] | None = field(default=None)


def build_spec() -> WorkflowSpec:
    data_engineer = AgentRole(
        role="data_engineer",
        tool_allowlist=["doc-parser:extract_text", "doc-parser:list_tables"],
    )
    qa_analyst = AgentRole(
        role="qa_analyst",
        tool_allowlist=["qa:check_consistency", "qa:fact_check"],
    )

    return (
        WorkflowSpec("finance_review_demo", name="Finance Review (demo)")
        .with_description(
            "Demonstrates a multi-role workflow with a mid-execution pause "
            "for user input."
        )
        .with_input(types=["document"], formats=["pdf"])
        .with_output(format="json")
        .use_servers("doc-parser", "qa")
        .use_tools(
            "doc-parser:extract_text",
            "doc-parser:list_tables",
            "qa:check_consistency",
            "qa:fact_check",
        )
        .add_phase("ingest", "Extract text + tables from the uploaded PDF.")
        .add_phase("review", "QA the extraction against ledger rules.")
        # Multi-role workflow — accepts a mix of bare role names and
        # AgentRole instances; instances with `tool_allowlist` auto-
        # populate the per-role allowlist map.
        .with_multi_role(
            active_specialists=[data_engineer, qa_analyst],
            workflow_context={"locale_hints": ["en"], "expected_doc_kind": "ledger"},
            autonomy_level="require_verification",
            max_total_tool_calls=40,
        )
        # Mid-execution resume boundary — pauses after `ingest` and asks
        # the user to disambiguate the fiscal year.
        .with_resume_boundary(
            "disambiguate_fiscal_year",
            after_phase="ingest",
            reason="Multiple fiscal years detected; need user choice before review.",
            slots=[
                SlotConfig(
                    slot_id="fiscal_year",
                    type="choice",
                    question="Which fiscal year should we review?",
                    options=["FY2024", "FY2025"],
                    required=True,
                ),
            ],
        )
    )


def main(argv: list[str]) -> int:
    spec = build_spec()
    compiled = spec.compile()

    # Sanity check: explicit specialists map could override; here we
    # rely on Protocol-derived allowlists.
    assert compiled["multi_agent"]["specialists"]["data_engineer"]["tools"] == [
        "doc-parser:extract_text",
        "doc-parser:list_tables",
    ]
    # RoleConfig round-trip sanity.
    config = RoleConfig.model_validate(
        compiled["multi_agent"]["specialists"]["data_engineer"]
    )
    assert config.tools[0] == "doc-parser:extract_text"

    out_path = Path(__file__).parent / "finance_review.spec.json"
    out_path.write_text(json.dumps(compiled, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")

    if "--print" in argv:
        print(json.dumps(compiled, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
