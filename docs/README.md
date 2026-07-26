# Convilyn SDK (author)

Build tool servers for the Convilyn AI workflow platform.

> **Companion package**: if you only want to *call* the Convilyn API
> (no server hosting), install
> [`convilyn`](https://pypi.org/project/convilyn/) instead. The two
> packages are intentionally separate so consumers don't pay the
> uvicorn dependency cost (`convilyn-author` wraps a lightweight
> internal MCP-over-uvicorn runtime, not FastAPI).

> **Free to install, paid to deploy.** `pip install convilyn-author` is
> free. You host your tool server on your own infrastructure (Lambda,
> Fargate, VM) at your own cost; Convilyn bills the *caller* of your
> tools, not you (see [DEPLOYMENT §8](./DEPLOYMENT.md#8-billing-model)).

## Quick Start

### Step 0 — get a developer key (`cvl_`)

The author track authenticates with a **developer** key (`cvl_` prefix) —
your consumer key (`ck_`, from the web console) will NOT work here. Mint
one by registering as a developer; there is no console UI for this yet:

```python
import asyncio
from convilyn_author import ConvilynClient

async def main() -> None:
    result = await ConvilynClient().register(
        email="you@example.com",
        name="Your Name",
        company="Optional Co.",
    )
    print(result["api_key"])   # cvl_… — shown ONCE, store it securely

asyncio.run(main())
```

Export it as `CONVILYN_API_KEY` (see Environment Variables below — the
client reads `CONVILYN_API_KEY`, not `CONVILYN_DEVELOPER_KEY`).
A 503 `REGISTRATION_STORE_UNAVAILABLE` response means the platform side
is temporarily unavailable — retry later; it is not a problem with your
request.

### Step 1 — scaffold a tool server

```bash
pip install convilyn-author
convilyn-author init my-server
cd my-server
```

> **Workflow authoring lives in the Convilyn chat Builder** (web console) —
> the canonical authoring surface. This is the **tool-server SDK**: build,
> register, verify and operate the MCP tool servers the platform's workflows
> call. The `WorkflowSpec` DSL and `submit_workflow` were removed in
> **2.3.0b1**; edge integrators export a Builder-built workflow's grounded
> contract via the consumer SDK (`client.user_workflows.grounded_contract(...)`).

Edit `server.py`:

```python
from convilyn_author import ConvilynServer

server = ConvilynServer(
    name="my-server",
    description="My custom tool server",
    version="1.0.0",
)

@server.tool(description="Process text input")
async def process(text: str) -> dict:
    return {"result": text.upper()}

if __name__ == "__main__":
    # Production entry point: requires CONVILYN_HMAC_SECRET (fail-closed).
    # For local development run `convilyn-author dev` instead — it serves
    # without a secret. Or pass server.run(dev=True) / set
    # CONVILYN_DEV_INSECURE=1 for a bare `python server.py` local run.
    server.run()
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `convilyn-author init <name>` | Scaffold a new project |
| `convilyn-author synth` | Compile → `convilyn.manifest.json` |
| `convilyn-author dev` | Start local server |
| `convilyn-author test` | Local compliance checks |
| `convilyn-author test --sandbox` | Test with Convilyn Sandbox Agent |
| `convilyn-author push --endpoint-url <url>` | Register a deployed tool server |
| `convilyn-author status` | Check tool-server verification status |
| `convilyn-author doctor` | Environment + connectivity checks |

## Testing

```python
from convilyn_author.testing import ConvilynTestRunner

runner = ConvilynTestRunner(server=server)
result = await runner.call_tool("process", {"text": "hello"})
assert result.success

report = await runner.run_compliance_check()
assert report.all_passed
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CONVILYN_API_KEY` | Your developer API key (`cvl_…`) — the name the client actually reads |
| `CONVILYN_PLATFORM_URL` | Platform base URL (default: `https://api.convilyn.corenovus.com`) |
| `CONVILYN_HOST` | Server bind host (default: `0.0.0.0`) |
| `CONVILYN_PORT` | Server bind port (default: `8080`) |
| `CONVILYN_HMAC_SECRET` | HMAC secret used to verify inbound `/mcp` requests from the Convilyn gateway. **Required on every deployment** — without it the server refuses to start (fail-closed). `convilyn-author dev` (and `CONVILYN_DEV_INSECURE=1`) serve without a secret for local development only. |
| `CONVILYN_HMAC_TOLERANCE_SECONDS` | Max clock skew vs gateway timestamp; default `300` (5 min) |
| `CONVILYN_LOG_LEVEL` | Log level (default: `INFO`) |

## Migrating from `convilyn` to `convilyn-author`

The legacy `convilyn` binary was removed in v2.0.0 — use `convilyn-author`.
The only change is the binary name; all sub-commands, flags, and behaviour
are identical:

```bash
# Before
convilyn init my-server
convilyn dev --port 8080
convilyn push --endpoint-url https://my-server.example.com

# After
convilyn-author init my-server
convilyn-author dev --port 8080
convilyn-author push --endpoint-url https://my-server.example.com
```

Why the rename: the consumer SDK (PyPI `convilyn`, the client for API
callers) also ships a `convilyn` binary. Two packages cannot coexist
in one environment while both claiming the same console script. The
author SDK now owns `convilyn-author`; the consumer SDK keeps `convilyn`.

## Next

* [DEPLOYMENT.md](./DEPLOYMENT.md) — Lambda / Fargate / VM walkthroughs + HMAC contract
* [STABILITY.md](./STABILITY.md) — what the public API is and the SemVer / deprecation promise behind it
* [CHANGELOG.md](../CHANGELOG.md) — version history
* [examples/](../examples/) — runnable example tool servers + workflows
* [AGENT.md](../AGENT.md) — guidance for AI coding agents contributing to this SDK

## Licence

Apache-2.0. See [`LICENSE`](../LICENSE).
