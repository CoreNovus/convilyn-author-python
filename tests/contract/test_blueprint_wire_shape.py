"""Blueprint wire-shape pin — the published cross-SDK / backend contract.

Once the author SDK is on PyPI, ``WorkflowSpec.compile()``'s output is a
frozen wire contract: the backend ``translate_blueprint`` and the chat
builder's unified authoring path (WS-B, #2135) both consume it. The
blueprint schema may only evolve **additively** — renaming or removing a
field, or switching away from snake_case, breaks every published SDK.

If a test here goes red, you are changing the published contract:
1. Additive change (new optional field): update the pin below AND confirm
   ``translate_blueprint`` still parses the OLD shape (backend regression
   test ``tests/contract/test_developer_portal_contract.py`` side).
2. Breaking change (rename / remove / re-case): bump
   ``PUBLIC_SCHEMA_VERSION`` and version the translator — do not silently
   edit the pin.
"""

from __future__ import annotations

from convilyn_author.workflow import WorkflowSpec
from convilyn_author.workflow_types import PUBLIC_SCHEMA_VERSION, WorkflowBlueprint

# The full public blueprint field set at PUBLIC_SCHEMA_VERSION == "1".
# snake_case throughout; ``spec_id`` and ``version`` are the identity keys
# the developer-portal's DestinationSpec parse requires (#2102 pinned the
# Python SDK as the compatible shape).
BLUEPRINT_V1_FIELDS = {
    "public_schema_version",
    "spec_id",
    "version",
    "name",
    "description",
    "description_i18n",
    "aliases",
    "keywords",
    "supported_input_types",
    "max_input_size_bytes",
    "max_input_duration_seconds",
    "min_input_duration_seconds",
    "supported_input_formats",
    "output_specs",
    "required_slots",
    "optional_slots",
    "preflight_rules",
    "locale_policy",
    "agent_config",
    "mcp_config",
    "phases",
    "multi_agent",
    "checkpoints",
    "task_policy",
    "routing",
    "qa_policy",
}


class TestBlueprintWireShape:
    def test_model_field_set_is_pinned(self):
        assert set(WorkflowBlueprint.model_fields) == BLUEPRINT_V1_FIELDS

    def test_public_schema_version_is_v1(self):
        assert PUBLIC_SCHEMA_VERSION == "1"

    def test_compile_emits_only_pinned_snake_case_keys(self):
        compiled = WorkflowSpec("pin_wf", name="Pin WF").compile()

        assert set(compiled) <= BLUEPRINT_V1_FIELDS

    def test_compile_carries_identity_keys(self):
        """The exact keys whose absence 422s the developer portal (#2102)."""
        compiled = WorkflowSpec("pin_wf", name="Pin WF", version="2.1.0").compile()

        assert {
            "spec_id": compiled.get("spec_id"),
            "version": compiled.get("version"),
            "public_schema_version": compiled.get("public_schema_version"),
        } == {
            "spec_id": "pin_wf",
            "version": "2.1.0",
            "public_schema_version": "1",
        }
