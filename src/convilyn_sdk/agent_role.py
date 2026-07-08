"""``AgentRole`` Protocol — authoring-side handle for a multi-role workflow.

When a workflow runs more than one cooperating role, the author needs a
way to declare which roles participate and what each role is allowed to
call. ``AgentRole`` is a structural Protocol: any frozen dataclass with
the right shape satisfies it, with no base class to inherit from.

Kept deliberately minimal — authoring-time concerns only. The Protocol
covers the two attributes the author SDK reads on its way to the wire
format: ``role`` (the canonical identifier) and ``tool_allowlist`` (an
optional per-role tool boundary). Widening this Protocol later is
non-breaking; narrowing it would be. Conform to ISP: the smallest useful
contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentRole(Protocol):
    """Authoring-side handle for a single role in a multi-role workflow.

    ``role`` is the canonical identifier the workflow uses to reference
    this role. ``tool_allowlist`` optionally narrows which tools this
    role may call; when ``None``, the SDK omits the entry entirely and
    the role inherits whatever tools the workflow declared.

    Authors can either:
    * pass a bare ``str`` (the role identifier only) to the multi-role
      builder method — the most common case — or
    * implement this Protocol (e.g. as a frozen dataclass) to bundle the
      role identifier with its tool boundary in a single object.
    """

    @property
    def role(self) -> str: ...

    @property
    def tool_allowlist(self) -> list[str] | None: ...
