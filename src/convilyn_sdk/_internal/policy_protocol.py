"""``PolicyProtocol`` — common shape every high-level policy knob conforms to.

The author-facing surface exposes five high-level knobs (retry, timeout,
output validation, human review, fallback). Each knob is a small data
class authored once and applied to a workflow via
``WorkflowSpec.with_policy(...)``. The Protocol below pins the minimum
shape the builder needs to know about:

* ``kind`` — the discriminator the translator registry dispatches on.
* ``to_wire()`` — the policy's projection into one or more wire blocks
  the platform consumes. Returning a multi-block dict lets a single
  knob span more than one wire slot (e.g. ``RetryPolicy`` writes both
  ``routing_policy.retry_policy`` and ``qa_policy.slot_policy.
  terminal_failure_policy`` simultaneously).

Authoring a new high-level knob is a two-step extension (OCP): define
the class implementing this Protocol, register a translator in
``policy_translator.py``. The builder never needs to grow a new method.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

PolicyKind = Literal[
    "retry",
    "timeout",
    "output_validation",
    "human_review",
    "fallback",
]


@runtime_checkable
class PolicyProtocol(Protocol):
    """Shape contract for every high-level policy knob.

    Implementations are typically frozen :class:`pydantic.BaseModel`
    subclasses, but anything with the right shape satisfies this
    Protocol (structural typing).
    """

    kind: PolicyKind

    def to_wire(self) -> dict[str, dict]:
        """Project this policy into one or more wire blocks.

        Returns a mapping from wire-block name (e.g. ``"routing_policy"``,
        ``"qa_policy"``, ``"task_policy"``) to the dict payload that the
        translator will MERGE into the compiled spec. A policy that only
        touches one wire block returns a single-entry dict; a policy
        that fans out to several returns one entry per touched block.
        """
        ...
