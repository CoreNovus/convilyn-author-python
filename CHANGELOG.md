# Changelog — `convilyn-author` (author SDK)

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.2.0b2] — 2026-07-12

### Docs

- **`register()` (and every client method) is an async coroutine — the
  docstrings now say so.** A bare `ConvilynClient().register(...)` from sync
  code returns an un-awaited coroutine and silently never sends the request;
  the `ConvilynClient` class docstring and the `register()` docstring now
  spell out the `await` / `asyncio.run(...)` requirement with an example.
  (Reported by an SDK user during the 2026-07-12 registration-outage
  investigation — the outage itself was a platform-side infrastructure gap,
  not an SDK defect; no calling-code change is needed once the platform
  answers 201.)
- **QUICKSTART now starts at the actual step 0**: minting a `cvl_` developer
  key via `ConvilynClient().register(...)` (the consumer `ck_` key does not
  work on the author track, and there is no console UI for developer
  registration yet). Also documents the server-less submission path for
  authors who cannot host a public endpoint.
- **Hosted-runtime error status corrected: 503, not 501.** Current platform
  builds answer `503 HOSTED_NOT_AVAILABLE` (older builds used 501;
  router-unmounted environments answer 404). `deploy --hosted`'s CLI hint now
  matches both codes (TS parity), and the `deploy_hosted_runtime` docstring
  and DEPLOYMENT.md no longer claim 501.

## [2.2.0b1] — 2026-07-11

### Added

- **Server-less workflow submission.** `submit_workflow(workflow_spec)` no
  longer requires `server_ids` — omit it (or pass an empty sequence) when
  your spec orchestrates only platform built-in tools (OCR / document
  parsing / analysis), the same shape every built-in goal-lane workflow
  uses. No self-hosted HMAC tool server is needed for that class of
  workflow, which unblocks edge/NAT authors who cannot expose a public
  endpoint. The platform still enforces the `dev_{prefix}.` spec namespace
  and warns on tool references it cannot resolve.

## [2.1.1b5] — 2026-07-10

### Fixed

- **`WorkflowSpec` name/tool-count bounds are now actually enforced.**
  2.1.1b4 added the check to the standalone `validate_workflow_spec()`
  pre-submission validator, but `WorkflowSpec.compile()` (the path every
  author and the community re-test actually exercises) never calls that
  function, so a 200-character name or 30 tool references still compiled
  successfully. The bound is now a `pydantic.Field` constraint on
  `WorkflowBlueprint.name` / `MCPConfigModel.tools`, enforced immediately
  at `use_tools()` / `compile()` time — the same place the TypeScript
  author SDK enforces it.

## [2.1.1b4] — 2026-07-10

### Added

- **Confirmation-handshake tokens**: `mint_confirmation_token` /
  `verify_confirmation_token` / `ConfirmationInvalidError` /
  `CONFIRMATION_TTL_SECONDS`, now exported from `convilyn_sdk`. Previously
  only the TypeScript author SDK implemented this despite the docs claiming
  Python compatibility — the wire format was always byte-for-byte compatible
  by specification, but the Python package didn't expose a function to use
  it. Port of `sdk/author-ts/src/confirmation.ts`.

### Fixed

- **`import convilyn_sdk` no longer crashes on Python 3.10.**
  `_internal/templates.py` used `from datetime import UTC` (Python 3.11+);
  now uses `datetime.timezone.utc`, which has always been available. (Not
  previously caught by testing because nothing exercised template
  installation on 3.10.)
- **`WorkflowSpec` now enforces the same `name` (≤80 chars) and tool-count
  (≤20) bounds as the TypeScript author SDK.** Previously a spec that
  compiled successfully in Python could still be rejected downstream by a
  TS-side or platform check applying the documented limit.
- **Tool-call JSON-RPC responses now carry `summary`/`status` fields**,
  matching the TypeScript author SDK's richer wire envelope
  (`tool-result-wire.ts`). Additive — the existing `success` / `data` /
  `error` / `execution_time_ms` fields are unchanged.
- Corrected the README/PyPI dependency description: `convilyn-author` wraps
  `uvicorn` + an internal MCP runtime, not FastAPI (the package has never
  depended on FastAPI).

## [2.1.1b3] — 2026-07-09

### Fixed

- Public-mirror CI is now green (same fixes as the consumer SDK: `ruff format`-clean
  source, `detect-secrets-hook` secret-scan, removed the broken typecheck step).
- Correct the generated public-repo README (it inherited the *consumer* tagline +
  a dead `docs/QUICKSTART.md` link) and `[project.urls]` — Issues / Repository /
  Changelog now point at `convilyn-author-python`, not the consumer repo.

### Changed

- Pin `ruff==0.15.6` in the `dev` extra and enforce `ruff format` on the SDK tree.

## [2.1.1b2] — 2026-07-08

### Docs

- Apache-2.0 licence line in the README + `AGENT.md` (were still "MIT").
- Valid `[project.urls] Issues` (was `mailto:`, which PyPI rejects).
- De-dup the v2.0.0 binary-rename note and remove references to the
  not-yet-published TypeScript / Go SDKs (Python is the only SDK live today).

## [2.1.1b1] — 2026-07-07

### Security

- **Template clone-source URLs get an extra safety check.** In addition
  to the exact-host allowlist, a clone target whose host resolves to a
  loopback, link-local, or private address is now rejected.

### Changed

- Docstrings, README, deployment guide, and CHANGELOG were revised for
  clarity; no public API changed.

## [2.1.0] — 2026-07-07

First published release (PyPI). `WorkflowBlueprint`
(`public_schema_version = "1"`) becomes the published wire contract from
this release on — it evolves additively only; see
`tests/contract/test_blueprint_wire_shape.py`.

> **Hosted runtime is gated in v2.1**: `convilyn-author deploy` targets
> the flag-gated Convilyn-Hosted runtime and the platform currently
> answers 501 — self-hosted serving via `serve()`/HMAC is the supported
> path. The gate exits with a clear message rather than half-deploying.

### Added

- **`ConvilynClient` rejects a consumer `ck_` key at construction** with a
  precise `ConvilynClientError`, instead of the developer portal answering with
  an opaque 401 later. The Author SDK authenticates with a `cvl_` developer key;
  an empty key (register() mints one) and any non-`ck_` prefix are still accepted
  (forward-compat). Mirror of the consumer SDKs' inverse guard.

### Fixed

- **`ConvilynClient` default base URL now includes `/api/v1`.** The
  Developer Portal is mounted at `/api/v1/developers/*`, but the client composed
  its base from `platform_url` alone (`https://api.convilyn.corenovus.com`) and
  appended relative `/developers/*` paths — so every call 404'd against the real
  backend. The default base now derives as `${platform_url}/api/v1`
  (idempotent); an explicitly-passed `base_url` is still
  used verbatim. Also fixes a stale unit assertion left red by the base-URL flip
  to `corenovus`.

### Security

- **Template-fork clone URLs are now allowlisted + SSRF-guarded
  follow-through).** The `git clone` URL in `fork_template` comes from the
  template package's PyPI `project_urls` — attacker-writable metadata. The
  old check was scheme-prefix only (`https://` / `git+https://`); a malicious
  `convilyn-template-*` package could point it at `https://169.254.169.254/…`
  or any private address. Now: exact-match host allowlist (github.com,
  gitlab.com, bitbucket.org, codeberg.org; extendable via
  `CONVILYN_TEMPLATE_CLONE_HOSTS`), userinfo and non-443 ports rejected, and
  a resolve-time private-address gate (`_internal/urlpolicy.py`, a vendored
  resolve-time SSRF check runs immediately before the
  subprocess — failure raises `TemplateError(code="UNSAFE_SOURCE_URL")` and
  `git` is never spawned. L2 IP-pinning is documented as not applicable to a
  subprocess; the residual TOCTOU is accepted and recorded in the audit.

### Changed

- **Default platform URL corrected to `https://api.convilyn.corenovus.com`**
  (was the non-serving `api.convilyn.com`), aligning every SDK's zero-config
  default with the live API host (cf. consumer-python commit 8864f05c7).

## [2.0.0] — 2026-07-01

### Removed

- **Legacy `convilyn` CLI alias** — the deprecated `convilyn` console-script
  (the `cli/_legacy_main.py` shim and its `CONVILYN_AUTHOR_BANNER_SHOWN`
  banner) is removed. The author SDK ships a single binary, `convilyn-author`;
  the `convilyn` binary belongs to the consumer SDK. This is a **breaking
  change**. Migration: `s/convilyn /convilyn-author /` in scripts.
- **Deprecated public surface dropped at the package root** —
  the back-compat names kept for one release during the `1.x` rename pass are
  gone in this major:
  - `Specialist` (top-level alias) and the `convilyn_sdk.specialist` import
    path → use `AgentRole` (`convilyn_sdk.agent_role`).
  - `SpecialistConfigModel` / `MultiAgentConfig` aliases → use `RoleConfig` /
    `MultiRoleConfig`.
  - `WorkflowSpec.with_multi_agent` / `with_checkpoint` methods → use
    `with_multi_role` / `with_resume_boundary`.
  - The 13 granular `*Config` policy models (`RetryPolicyConfig`,
    `FallbackPolicyConfig`, `GoalCriteriaConfig`, `QaPolicyConfig`,
    `QualityCheckConfig`, `RoutingPolicyConfig`, `SectionConfig`,
    `SlotPolicyConfig`, `StructuralCheckConfig`, `TaskPolicyConfig`,
    `TerminalFailurePolicyConfig`, `ToolStageConfig`, `FailureRuleConfig`) are
    no longer re-exported at the package root. Prefer the five high-level knobs
    in `convilyn_sdk.policies`; the typed granular models stay importable from
    `convilyn_sdk.workflow_policies` (advanced, non-SemVer surface) for the
    granular `with_task_policy` / `with_routing` / `with_qa_policy` builders.
- Retired the `docs/STABILITY.md` deprecation register now that its whole
  cohort has been removed.

### Added

- **Public-API contract test** (`tests/contract/test_public_surface.py`) —
  freezes `convilyn_sdk.__all__`, the core abstractions' contract methods
  (`ToolServer` / `WorkflowSpec` / `ConvilynManifest` / `ToolCatalog`), and the
  `convilyn-author` CLI command tree, and fails if any `convilyn_sdk._internal`
  symbol leaks into the public namespace or the surface grows implicitly. The
  keystone guard behind the SemVer promise; see `docs/STABILITY.md`.
- **`docs/STABILITY.md`** — the published stability & versioning policy: what the
  public surface is (`convilyn_sdk.__all__` + the `convilyn-author` CLI + the
  HMAC/manifest wire shapes), the SemVer table, the `_internal` exemption, and a
  **deprecation register**.
- **`convilyn-author template {list,install,fork}`** — Git-workflow
  marketplace for tool-server templates under the
  ``convilyn-template-*`` PyPI namespace.
  - `template list [--query=X]` queries the PyPI simple index and
    filters by the namespace prefix.
  - `template install <name>` runs `pip install convilyn-template-<name>`
    and records the entry in `~/.convilyn/templates.json` (overridable
    via `CONVILYN_TEMPLATE_CATALOG`).
  - `template fork <name> <new_name>` reads the template's PyPI
    metadata for the source repo URL, `git clone`s it into
    `./<new_name>`, rewrites `pyproject.toml` + README to the new
    name, and strips `.git/` so the fork starts with a clean history.
  - Complements the in-app community marketplace —
    that surface is for end-user discovery; this one is for author
    workflows where Git + IDE ergonomics matter more.

- **`convilyn-author deploy --hosted --region <r>`** — deploy a tool
  server (and optional workflow spec) to the Convilyn-Hosted Author
  Runtime. The platform provisions a sandboxed hosted runtime inside the
  Convilyn-owned AWS account and returns a public endpoint URL.
  Without `--hosted` the command errors and points at `push` —
  caller-deployed (BYO) deployments stay on the existing
  `convilyn-author push --endpoint-url ...` flow. **Preview**: requires
  the platform-side hosted-runtime API to be enabled; until then the
  CLI surfaces a `HOSTED_NOT_AVAILABLE` 501 with a BYO fallback hint.
- **`convilyn-author rollback <runtime_id>`** — flip the runtime's
  hosted runtime to its previous active version (retention keeps
  the last 20 images per author).
- **`convilyn-author logs <runtime_id> [--since=5m] [--limit=100]`** —
  fetch recent logs for a hosted runtime. The `since`
  argument is forwarded verbatim to the platform (relative
  shorthand or ISO-8601).
- **`ConvilynClient.deploy_hosted_runtime` /
  `rollback_hosted_runtime` / `get_hosted_runtime_logs`** — Python
  equivalents of the new CLI verbs. The logs method tolerates either
  a bare list or `{"entries": [...]}` wire envelope.

- **Five high-level policy knobs** — the new author-facing surface for
  policy composition: `RetryPolicy`, `TimeoutPolicy`,
  `OutputValidationPolicy`, `HumanReviewPolicy`, `FallbackPolicy`. Each
  knob is a small data class conforming to `PolicyProtocol`; apply one
  or more to a workflow via `WorkflowSpec.with_policy(*policies)`. The
  SDK translates each knob into the appropriate wire blocks and
  composes them deterministically. Duplicate kinds and overlapping
  wire leaves raise `ValueError`.

### Changed

- Renamed authoring Protocol `Specialist` → `AgentRole`; new canonical
  module path is `convilyn_sdk.agent_role`. The old `Specialist` name
  remains as a back-compat alias at the package root, and
  `convilyn_sdk.specialist` keeps re-exporting it with a
  `DeprecationWarning`.
- Renamed builder methods: `WorkflowSpec.with_multi_agent(...)` →
  `with_multi_role(...)`, `WorkflowSpec.with_checkpoint(...)` →
  `with_resume_boundary(...)`. The old method names remain as thin
  wrappers that emit a `DeprecationWarning` and forward to the new
  ones; existing call sites keep working unchanged.
- Renamed config models: `MultiAgentConfig` → `MultiRoleConfig`,
  `SpecialistConfigModel` → `RoleConfig`. The old names remain as
  silent back-compat aliases.
- Internal layout: the thirteen granular policy config models have
  moved to `convilyn_sdk._internal.legacy_policies`; they stay importable
  under their original names from `convilyn_sdk.workflow_policies` (the
  advanced, non-SemVer surface). New code should prefer the high-level knobs.
- `ToolServer.run()` gained a keyword-only `dev: bool = False`
  parameter (backward-compatible) that opts into insecure local
  serving (see Security below).

### Fixed

- Relocated the package directory under `sdk/author-python/` (alongside the
  other SDKs under `sdk/`) for naming parity with `sdk/consumer-python`.
  Updated all path references (publish
  workflow, dependabot, blackbox-lint scan roots, `[project.urls]`, docs links,
  `.gitignore`). The PyPI package name (`convilyn-author`) and import name
  (`convilyn_sdk`) are unchanged.
- Expanded the `convilyn_sdk` package docstring to show an accurate `ToolServer`
  + `WorkflowSpec` quickstart and name the public-API stability contract.
- `convilyn-author init` / `workflow init` next-step hints now reference the
  `convilyn-author` binary (they still printed the removed legacy `convilyn`
  alias, e.g. `convilyn dev`).

### Security

- **Inbound `/mcp` verification is now fail-closed by default.** Previously a
  tool server with no `CONVILYN_HMAC_SECRET` served unsigned requests whenever
  `is_local` was true — and `CONVILYN_ENVIRONMENT` defaults to `"local"`, so a
  self-hosted Fargate/VM deployment that simply forgot to set the secret served
  `/mcp` **open to anyone**, contradicting `docs/DEPLOYMENT.md`'s "the HMAC check
  IS your authn". The server now **refuses to start** (and rejects `/mcp` with
  401) without a secret unless insecure local development is opted into
  *explicitly*: `convilyn-author dev` (passes `dev=True`), `ToolServer.run(dev=True)`,
  or `CONVILYN_DEV_INSECURE=1`. The ambient environment / bind host are no longer
  consulted as an auth signal. **Behaviour change:** a bare `python server.py`
  with no secret now needs `CONVILYN_DEV_INSECURE=1` to run insecurely — see
  `docs/STABILITY.md` and `docs/DEPLOYMENT.md`.
- **Template name validation** (`convilyn-author template install/fork`) now
  anchors with `\Z` instead of `$`, rejecting a trailing-newline suffix
  (`"name\n"`) that the old anchor allowed. Defence-in-depth — argv was already a
  closed list, so this was not exploitable.

## [1.2.0] — 2026-06-30

### Changed (pre-publish breaking reshape — package not yet on PyPI)

- **`compile()` now emits a sanitized public `WorkflowBlueprint`, not the
  internal spec shape.** The author SDK no longer exposes the platform's
  internal workflow contract. The blueprint carries author *intent* only
  (identity, i18n/discovery, input/output, slots, preflight, locale, phase
  *descriptions*, tool refs, high-level policy knobs) plus a
  `public_schema_version`. The platform translates the blueprint into the real
  executable form server-side; internal engine
  details are **never** emitted
  by the SDK, so the engine contract can evolve without breaking published SDKs.

### Removed (pre-publish)

- `WorkflowSpec.with_variant`, `with_subcategory`, `with_sku_group`,
  `with_priority`, `with_default_steps`, `with_progress_milestones` — these set
  platform-internal fields that are now derived server-side by the translator.
- `with_agent_config(system_prompt_id=…, min_tools_for_auto=…)` parameters and
  `AgentConfigModel.{system_prompt_id, min_tools_for_auto,
  tool_progress_milestones}` — prompt-template selection and engine tuning are
  platform-owned. Authors may still pass their own `system_prompt` text.
- `workflow_types.CompiledWorkflowSpec` is renamed to `WorkflowBlueprint`
  (a back-compat alias is retained for internal imports).

## [1.1.0] — 2026-05-24

### Added

- **`convilyn-author` CLI binary** — the new canonical console script
  for the author SDK. Resolves the long-standing collision with the
  consumer SDK's `convilyn` binary. All sub-commands (`init`, `synth`,
  `dev`, `test`, `workflow init|build`, `push`, `status`, `doctor`)
  reachable under the new name.
- **`WorkflowSpec.with_multi_agent(...)`** — opt a workflow into
  multi-role execution. Accepts bare role strings OR objects satisfying
  the `AgentRole` Protocol (auto-populates the per-role tool allowlist
  via DIP). Renamed to `with_multi_role` in the unreleased entry above.
- **`WorkflowSpec.with_checkpoint(...)`** — additive mid-execution
  pause points (one call per checkpoint; chainable). Renamed to
  `with_resume_boundary` in the unreleased entry above.
- **`WorkflowSpec.with_task_policy / with_routing / with_qa_policy`**
  — fluent surfaces for the bounded `ClarifyCondition` /
  `InferCondition` / `StopCondition` / `FailureCategory` / etc.
  vocabularies. The unreleased entry above introduces five higher-level
  policy knobs that compose these blocks via a translator.
- **9 Literal aliases for policy vocabularies**: `ClarifyCondition`,
  `InferCondition`, `StopCondition`, `NoToolResultAction`,
  `FailureCategory`, `QaSlotType`, `FirstQuestionFormat`,
  `QualityCheckType`, `StructuralCheckType`.
- **13 Pydantic sibling models**: `MultiRoleConfig`,
  `CheckpointConfig`, `RoleConfig`, `TaskPolicyConfig`,
  `RoutingPolicyConfig`, `QaPolicyConfig` + nested models. All
  `extra="allow"` for OCP-aligned forward-compat.
- **`docs/DEPLOYMENT.md`** — comprehensive walkthrough of the three
  supported deployment targets (AWS Lambda Docker, AWS Fargate, plain
  VM). Documents HMAC contract, env-var matrix, and the BYO hosting
  model explicitly.

### Changed

- **Legacy `convilyn` binary**: still works through v1.x. Emits a
  one-time deprecation banner on stderr on first invocation in a
  process. Silence with `CONVILYN_AUTHOR_BANNER_SHOWN=1`. Scheduled for
  removal in v2.0.0.
- **Version source-of-truth**: now lives in `src/convilyn_sdk/_version.py`
  (read by both pyproject metadata and the runtime `__version__`
  attribute). Previously drifted between hardcoded constants in two
  places.
- **License**: moved from speculative `Apache-2.0` placeholder to `MIT`
  (matches the repo's existing precedent under `llm-gateway/LICENSE`).

### Deprecated

- `convilyn` (without the `-author` suffix) as the author SDK's binary
  name. Removed in v2.0.0.

## [1.0.0] — 2026-05

Initial author-SDK release: `ToolServer` + `WorkflowSpec` (partial
coverage of the workflow spec surface), HMAC-verified uvicorn runtime,
`init` / `synth` / `dev` / `test` / `push` / `status` CLI commands.
Published as `convilyn-author` on PyPI.
