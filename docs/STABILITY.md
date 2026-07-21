# Stability & versioning policy

`convilyn-author` (the **author** SDK, import package `convilyn_author`) follows
[Semantic Versioning](https://semver.org/). This page defines exactly **what is
covered by that promise** so you know what you can depend on and what may change
underneath you.

## The public surface

The public, semver-covered surface of this package is:

1. **Everything reachable as `from convilyn_author import X`** — i.e. every name in
   `convilyn_author.__all__`. That is the server + workflow builders (`ToolServer`,
   `WorkflowSpec`), the platform client (`ConvilynClient`), the catalog and
   manifest (`ToolCatalog`, `ConvilynManifest`), the execution context
   (`ToolContext`), the data-store abstraction (`InMemoryDataStore`), the
   high-level policy knobs (`RetryPolicy`, `TimeoutPolicy`,
   `OutputValidationPolicy`, `HumanReviewPolicy`, `FallbackPolicy`, …), and the
   typed DTOs (`ToolSpec`, `ToolResult`, `ToolError`, `ToolDataRef`,
   `ComplianceResult`, …).
2. **The public testing helpers** under `convilyn_author.testing`
   (`ConvilynTestRunner`, `WorkflowTestRunner`, `assert_tool_success`, …).
3. **The `convilyn-author` CLI** — command names, documented flags, and output
   shape: `init`, `synth`, `dev`, `test`, `push`, `deploy`, `rollback`, `logs`,
   `status`, `doctor`, plus `workflow {init,build}` and
   `template {list,install,fork}`.
4. **The HMAC inbound-verification contract** and the compiled manifest a
   deployed tool server exchanges with the platform gateway.
5. **The `WorkflowBlueprint`** that `WorkflowSpec.compile()` emits — its public
   field set plus `public_schema_version`. The blueprint is a *sanitized*
   authoring shape, **not** the platform's internal workflow spec: the platform
   translates the blueprint server-side into the real spec, so internal engine
   details are intentionally **not** part of this
   public surface and may change without a blueprint version bump. A breaking
   change to the blueprint itself bumps `public_schema_version`.

A test guards this surface: `tests/contract/test_public_surface.py` freezes
`convilyn_author.__all__`, the core abstractions' contract methods, and the CLI
command tree, and asserts that nothing from `convilyn_author._internal` leaks into
the public namespace. Any deliberate change to the public surface must update
that test **and** the [CHANGELOG](../CHANGELOG.md) in the same commit.

## What is NOT public

- **`convilyn_author._internal.*`** — HMAC signature verification, the JSON-RPC
  protocol adapter and DTOs, the FastMCP server runtime, the policy translator,
  and the template-marketplace internals. These have **no stability guarantee**
  and may change or move in any release. Never import from
  `convilyn_author._internal`.
- **Any attribute or method whose name starts with `_`.**

## SemVer in practice

| Change | Version bump |
|---|---|
| Remove/rename a public symbol, remove a CLI command/flag, change the manifest/HMAC wire shape, narrow a method signature | **major** (`X`) |
| Add a new public symbol, abstraction method, CLI command/flag, or policy knob — backward compatible | **minor** (`Y`) |
| Bug fix, doc fix, internal refactor with no public-surface change | **patch** (`Z`) |

## Deprecation register

There is currently **no deprecated public surface**. The `1.x` deprecation
cohort (the `Specialist` alias + `convilyn_author.specialist` path, the
`SpecialistConfigModel`/`MultiAgentConfig` aliases, the
`WorkflowSpec.with_multi_agent`/`with_checkpoint` methods, and the top-level
re-export of the 13 granular `*Config` policy models) was **removed in 2.0.0** —
see the removal record below. New deprecations will be listed here with their
replacement and removal release.

The 13 granular `*Config` policy models are **not** gone: they remain importable
from `convilyn_author.workflow_policies` (the advanced, non-semver surface the
granular `with_task_policy` / `with_routing` / `with_qa_policy` builders
compose). Only their top-level `from convilyn_author import *Config` re-export was
dropped; prefer the five high-level knobs in `convilyn_author.policies`.

## Behaviour changes

| Version | Change |
|---|---|
| **2.0.0** | Removed the `1.x` deprecation cohort: `Specialist` (top-level alias) and the `convilyn_author.specialist` import path → `AgentRole`; `SpecialistConfigModel` / `MultiAgentConfig` aliases → `RoleConfig` / `MultiRoleConfig`; `WorkflowSpec.with_multi_agent` / `with_checkpoint` → `with_multi_role` / `with_resume_boundary`; the top-level re-export of the 13 granular `*Config` models (still importable from `convilyn_author.workflow_policies`). The legacy `convilyn` CLI alias was also removed (use `convilyn-author`). |
| **1.2.0** | Inbound `/mcp` HMAC verification is **fail-closed**. A server with no `CONVILYN_HMAC_SECRET` now refuses to start and rejects `/mcp` with 401 unless insecure local dev is opted into explicitly (`convilyn-author dev`, `ToolServer.run(dev=True)`, or `CONVILYN_DEV_INSECURE=1`). Previously an unset `CONVILYN_ENVIRONMENT` (default `"local"`) silently served unsigned requests — including on deployed self-hosted servers. This is a security fix; the public symbol surface is unchanged (`run()` gained a backward-compatible keyword-only `dev` parameter). |
