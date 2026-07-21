"""Advanced typed-policy surface — the granular wire-shape config models.

The *recommended* author-facing surface is the five high-level knobs in
:mod:`convilyn_author.policies` (``RetryPolicy``, ``TimeoutPolicy``,
``OutputValidationPolicy``, ``HumanReviewPolicy``, ``FallbackPolicy``),
re-exported at the package root and covered by the SemVer promise.

This module is the layer *below* them: the granular ``*Config`` wire
models (canonical home: :mod:`convilyn_author._internal.legacy_policies`)
plus the bounded ``Literal`` vocabularies. It is intentionally **not**
part of ``convilyn_author.__all__`` — it carries no stability guarantee —
but stays importable as ``convilyn_author.workflow_policies`` for two
reasons:

* the granular builder methods ``WorkflowSpec.with_task_policy`` /
  ``with_routing`` / ``with_qa_policy`` construct these models, and
* it keeps the granular models off the ``_internal`` import path so
  :mod:`convilyn_author.workflow` never reaches into ``_internal``
  (see ``AGENT.md`` — forbidden patterns).

Prior to v2.0.0 these names were also re-exported at the package root;
that top-level re-export was removed in the 2.0.0 major. Power users who
want typed granular control import from here; everyone else should
prefer the five high-level knobs.
"""

from __future__ import annotations

from convilyn_author._internal.legacy_policies import (
    ClarifyCondition,
    FailureCategory,
    FailureRuleConfig,
    FallbackPolicyConfig,
    FirstQuestionFormat,
    GoalCriteriaConfig,
    InferCondition,
    NoToolResultAction,
    QaPolicyConfig,
    QaSlotType,
    QualityCheckConfig,
    QualityCheckType,
    RetryPolicyConfig,
    RoutingPolicyConfig,
    SectionConfig,
    SlotPolicyConfig,
    StopCondition,
    StructuralCheckConfig,
    StructuralCheckType,
    TaskPolicyConfig,
    TerminalFailurePolicyConfig,
    ToolStageConfig,
    _coerce_to_model,
)

__all__ = [
    "ClarifyCondition",
    "FailureCategory",
    "FailureRuleConfig",
    "FallbackPolicyConfig",
    "FirstQuestionFormat",
    "GoalCriteriaConfig",
    "InferCondition",
    "NoToolResultAction",
    "QaPolicyConfig",
    "QaSlotType",
    "QualityCheckConfig",
    "QualityCheckType",
    "RetryPolicyConfig",
    "RoutingPolicyConfig",
    "SectionConfig",
    "SlotPolicyConfig",
    "StopCondition",
    "StructuralCheckConfig",
    "StructuralCheckType",
    "TaskPolicyConfig",
    "TerminalFailurePolicyConfig",
    "ToolStageConfig",
    "_coerce_to_model",
]
