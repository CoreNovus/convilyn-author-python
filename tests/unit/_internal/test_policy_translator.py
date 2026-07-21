"""Drift detector — SDK Literal vocabularies vs backend authoritative.

The author SDK re-declares Pydantic ``Literal`` aliases verbatim from
the backend schema modules (the umbrella's "no backend imports from
the SDK" rule means we cannot import the backend types directly at
runtime — that would couple the wheel to a backend dep we don't
ship).

This test bridges that gap **at test time only** with
:func:`pytest.importorskip` — in monorepo CI the backend is on
``sys.path`` and the test runs; for SDK-only contributors (or PyPI
wheel CI) the backend module isn't importable and the test
``skip``s without failing.

The monorepo CI workflow should additionally assert that
``test_skipped == 0`` so the drift detector cannot silently disappear.
"""

from __future__ import annotations

from typing import get_args

import pytest


@pytest.fixture(scope="module")
def backend_task_policy():
    return pytest.importorskip("app.orchestrator.specs.schema.task_policy")


@pytest.fixture(scope="module")
def backend_routing_policy():
    return pytest.importorskip("app.orchestrator.specs.schema.routing_policy")


@pytest.fixture(scope="module")
def backend_qa_policy():
    return pytest.importorskip("app.orchestrator.specs.schema.qa_policy")


# ── task_policy parity ──────────────────────────────────────────────


class TestTaskPolicyParity:
    def test_clarify_condition_values_match(self, backend_task_policy) -> None:
        from convilyn_author.workflow_policies import ClarifyCondition

        assert get_args(ClarifyCondition) == get_args(backend_task_policy.ClarifyCondition)

    def test_infer_condition_values_match(self, backend_task_policy) -> None:
        from convilyn_author.workflow_policies import InferCondition

        assert get_args(InferCondition) == get_args(backend_task_policy.InferCondition)

    def test_stop_condition_values_match(self, backend_task_policy) -> None:
        from convilyn_author.workflow_policies import StopCondition

        assert get_args(StopCondition) == get_args(backend_task_policy.StopCondition)


# ── routing parity ──────────────────────────────────────────────────


class TestRoutingPolicyParity:
    def test_no_tool_result_action_matches(self, backend_routing_policy) -> None:
        from convilyn_author.workflow_policies import NoToolResultAction

        backend_field = backend_routing_policy.FallbackPolicy.model_fields["no_tool_result"]
        # The Literal is the type annotation of the backend field.
        backend_literal_args = get_args(backend_field.annotation)
        assert get_args(NoToolResultAction) == backend_literal_args


# ── qa_policy parity ────────────────────────────────────────────────


class TestQaPolicyParity:
    def test_failure_category_values_match(self, backend_qa_policy) -> None:
        from convilyn_author.workflow_policies import FailureCategory

        assert get_args(FailureCategory) == get_args(backend_qa_policy.FailureCategory)

    def test_slot_type_values_match(self, backend_qa_policy) -> None:
        from convilyn_author.workflow_policies import QaSlotType

        assert get_args(QaSlotType) == get_args(backend_qa_policy.SlotType)

    def test_first_question_format_matches(self, backend_qa_policy) -> None:
        from convilyn_author.workflow_policies import FirstQuestionFormat

        backend_field = backend_qa_policy.SlotPolicy.model_fields["first_question_format"]
        # Field annotation is `Literal[...] | None`; unwrap the Optional.
        # We compare against the Literal args, not the | None outer type.
        from typing import Union, get_origin
        from typing import get_args as _get_args

        annotation = backend_field.annotation
        if get_origin(annotation) is Union:
            literal_arg = next(arg for arg in _get_args(annotation) if arg is not type(None))
        else:
            literal_arg = annotation
        assert get_args(FirstQuestionFormat) == get_args(literal_arg)

    def test_quality_check_type_matches(self, backend_qa_policy) -> None:
        from convilyn_author.workflow_policies import QualityCheckType

        backend_field = backend_qa_policy.QualityCheck.model_fields["type"]
        assert get_args(QualityCheckType) == get_args(backend_field.annotation)

    def test_structural_check_type_matches(self, backend_qa_policy) -> None:
        from convilyn_author.workflow_policies import StructuralCheckType

        backend_field = backend_qa_policy.StructuralCheck.model_fields["type"]
        assert get_args(StructuralCheckType) == get_args(backend_field.annotation)
