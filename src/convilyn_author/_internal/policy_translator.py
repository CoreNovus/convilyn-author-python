"""Strategy registry mapping high-level policies to wire-block payloads.

Each high-level policy class implements :class:`PolicyProtocol` with a
``to_wire()`` method. This module's only job is to take a sequence of
policies, ask each one for its wire-block contribution, and MERGE the
contributions into the spec's policy-block dict — deterministically and
with conflict detection.

The merge is deep on dicts and list-replace on lists; two policies
contributing to the same wire-block key are an authoring error (the
caller passed two ``RetryPolicy`` instances, say) and raise
:class:`ValueError`.

Adding a new high-level policy is a one-line change: the policy itself
implements ``PolicyProtocol``; this module does not need editing (OCP).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from convilyn_author._internal.policy_protocol import PolicyProtocol


def merge_wire_blocks(
    base: dict[str, Any], addition: dict[str, Any], path: str = ""
) -> dict[str, Any]:
    """Deep-merge ``addition`` into ``base``. Raise on overlapping leaves.

    Used by :func:`apply_policies` to fold each policy's wire output
    into the running spec dict without silent overwrites.
    """
    merged = dict(base)
    for key, value in addition.items():
        leaf_path = f"{path}.{key}" if path else key
        if key not in merged:
            merged[key] = value
            continue
        existing = merged[key]
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_wire_blocks(existing, value, leaf_path)
        elif existing == value:
            continue
        else:
            raise ValueError(
                f"Policy conflict at wire block {leaf_path!r}: "
                f"existing={existing!r} vs incoming={value!r}"
            )
    return merged


def apply_policies(
    policies: Sequence[PolicyProtocol], existing_blocks: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Translate a sequence of high-level policies into wire blocks.

    Returns a mapping ``{block_name: payload_dict}`` ready for the spec
    builder to deep-merge into its compiled output. Duplicate ``kind``
    values raise :class:`ValueError` — the author meant to compose
    *different* knobs, not stack two retry policies.
    """
    seen_kinds: set[str] = set()
    blocks: dict[str, Any] = dict(existing_blocks or {})
    for policy in policies:
        if policy.kind in seen_kinds:
            raise ValueError(
                f"Duplicate policy kind {policy.kind!r}; supply at most "
                f"one of each high-level knob per workflow."
            )
        seen_kinds.add(policy.kind)
        contribution = policy.to_wire()
        blocks = merge_wire_blocks(blocks, contribution)
    return blocks
