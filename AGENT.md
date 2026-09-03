# AGENT.md — guidance for AI coding agents (author SDK)

This file is for AI coding agents (Claude Code, Cursor, Cline,
Aider, Windsurf, GitHub Copilot Workspace) that open this directory
and want to extend the Convilyn **author** SDK (`convilyn-author`) without
breaking it. Read this first; it documents the invariants that the
test suite will defend.

> **Consumer vs author**: this is the SDK third-party developers use to
> *build* tool servers FOR Convilyn. The companion
> consumer SDK at `../consumer-python/` (PyPI `convilyn`) is what API
> callers use. They have separate `__init__.py`, separate PyPI
> identities, and separate CLI binaries (`convilyn-author` here,
> `convilyn` there).

## Where things live

```
sdk/author-python/                       # PyPI: convilyn-author
├── pyproject.toml                # one source of truth for deps + scripts
├── LICENSE                       # Apache-2.0
├── CHANGELOG.md                  # Keep-a-Changelog format
├── docs/
│   ├── README.md                 # PyPI landing page
│   └── DEPLOYMENT.md             # Lambda / Fargate / VM walkthroughs + HMAC contract
├── examples/                     # runnable example tool servers
├── src/convilyn_author/
│   ├── __init__.py               # public surface — only re-exports
│   ├── _version.py               # single source of truth for __version__
│   ├── server.py                 # ToolServer — the @server.tool decorator
│   ├── client.py                 # ConvilynClient — push to platform
│   ├── manifest.py               # ConvilynManifest — compiled blueprint
│   ├── catalog.py                # ToolCatalog
│   ├── context.py                # ToolContext
│   ├── config.py                 # SDKConfig — env-based configuration
│   ├── data_store.py             # InMemoryDataStore + DataStoreProtocol
│   ├── types.py                  # ToolSpec / ToolError / ToolResult / ...
│   ├── testing/                  # ConvilynTestRunner harness
│   ├── cli/
│   │   ├── main.py               # Click CLI (`convilyn-author`)
│   │   └── scaffold.py           # project scaffolding templates
│   └── _internal/                # NOT public — protocol, auth, server_runtime
└── tests/                        # one test file per module
```

## Public surface contract

Anything reachable as `from convilyn_author import X` is public and
follows semver. Treat `convilyn_author._internal.*` as private — agents
can read it, but should not import from it in new tool servers or
examples.

## SOLID seams already in place

These are the extension points. Use them; do not duplicate them.

| Seam | Purpose | Where |
|---|---|---|
| `@server.tool` decorator | Register a Python function as an MCP tool | `server.py::ToolServer.tool` |
| `DataStoreProtocol` | Plug an alternative tool-result store (DynamoDB, S3, in-process …) | `data_store.py` |
| `ConvilynClient` | HMAC-signed HTTP client to push tool servers | `client.py` |
| `ConvilynTestRunner` | Local compliance + dry-run harness | `testing/runner.py` |

> **Workflow authoring is not part of this SDK.** Workflows are authored in the
> Convilyn chat Builder; this is the tool-server SDK. The `WorkflowSpec` DSL was
> removed in 2.3.0b1.

## Adding a new CLI sub-command

1. Add the function in `cli/main.py` (or extract into a sibling module
   if it grows beyond ~50 lines).
2. Register with `@cli.command()` or `@cli.group()` — Click handles
   dispatch.
3. Re-use the standard loader: `_load_server_from_file` (`cli/main.py`)
   for any command that touches `server.py`.
4. Add a test mirroring the pattern in `tests/unit/cli/test_main.py`
   (CliRunner for Click commands; sys.argv patching + capsys for any plain
   entry-point functions).
5. Update `docs/README.md`'s CLI table.

## Testing rules

- **No real backend calls in unit tests.** Use `respx` to mock HTTP
  (mirrors the consumer SDK convention) and `tmp_path` for filesystem.
- **Four categories per behaviour**: logic, boundary, error,
  object-state. The unit-testing skill documents this in detail.

## Conventions

- `from __future__ import annotations` at the top of every module so
  forward references just work.
- Pydantic v2 with `populate_by_name=True` so SDK fields use Python
  snake_case while the wire stays camelCase.
- `ConfigDict(extra="allow")` on every sibling Pydantic model — OCP
  forward-compat with backend additions.
- Behaviour on the resource, data on the model — the OpenAI /
  Stripe convention. Do not put HTTP calls on the data models.

## Forbidden / discouraged patterns

- Importing from `convilyn_author._internal` outside `_internal` and `cli/`.
- Re-implementing HMAC verification — `_internal/auth.py::verify_signature`
  is the single source of truth.
- Adding fluent methods that bypass the `_clone()` immutability pattern.
- Editing `__version__` in `__init__.py` — bump `_version.py` instead.
- Calling `time.sleep` anywhere in async code paths (use
  `await asyncio.sleep`).

## When you're stuck

- Read the relevant test file — the test names spell out the contract
  for the module.
- `convilyn-author doctor` for environment / connectivity issues.
- `convilyn-author --help` for the full command tree.
- Open an issue at <https://github.com/CoreNovus/convilyn/issues>
  with a minimal repro and the output of `convilyn-author doctor`.

## See also

- Consumer SDK: `../consumer-python/AGENT.md` (the SDK API callers use).
- Deployment walkthroughs: `docs/DEPLOYMENT.md`.
- Public docs: <https://docs.convilyn.com>.
