# Deploying a Convilyn Author Tool Server

This guide walks through hosting a `ToolServer` built with `convilyn-author`
so the Convilyn platform can call into it. Three deployment targets are
documented end-to-end: **AWS Lambda (Docker)**, **AWS Fargate**, and a
**plain VM / container with HTTPS frontend**.

> **Hosting model.** Convilyn does NOT host author tool servers today.
> The SDK ships a uvicorn-based ASGI runtime intended for your own
> infrastructure. `convilyn-author push` only *registers* an
> already-reachable endpoint URL with the platform — Convilyn then
> calls back into that endpoint over HTTPS with HMAC-signed requests.
>
> A managed hosted-runtime offering is on the roadmap; this
> document covers the BYO path that is available today.

## 1. Prerequisites

- A working `ToolServer` defined in `server.py` (see [README](README.md))
- HTTPS-terminating endpoint reachable from the public internet
- Ability to set environment variables on your runtime
- A `cvl_` developer API key from <https://console.corenovus.com/keys>

## 2. HMAC contract (read first)

Every inbound request from Convilyn carries three headers:

| Header | Purpose |
|---|---|
| `X-Convilyn-Server-Id` | Identifies which registered server is being called |
| `X-Convilyn-Timestamp` | Unix-seconds at the gateway; rejected if more than 5 min stale |
| `X-Convilyn-Signature` | HMAC-SHA256 over `timestamp + "." + body_bytes` |

The SDK verifies all three automatically when `CONVILYN_HMAC_SECRET` is
set (see env vars below).

**Verification is fail-closed: the server refuses requests it cannot
verify.** Any server started without
`CONVILYN_HMAC_SECRET` **refuses to boot** (`ConvilynStartupError`) and
rejects `/mcp` with `401` — regardless of `CONVILYN_ENVIRONMENT` or the
bind host. **You must set the secret on every deployment.** Insecure local
development without a secret is allowed only when you opt in *explicitly*:

- `convilyn-author dev` — the local dev command opts in for you, or
- `CONVILYN_DEV_INSECURE=1` — for a bare `python server.py` run.

Never set `CONVILYN_DEV_INSECURE` in a deployed environment.

## 3. Environment variables (all deployments)

| Variable | Required? | Description |
|---|---|---|
| `CONVILYN_HMAC_SECRET` | **yes (all deployments)** | Secret used to verify inbound HMAC signatures. Without it the server refuses to start. |
| `CONVILYN_DEV_INSECURE` | local dev only | Set to `1` to serve `/mcp` WITHOUT signature verification. INSECURE — never set in a deployed environment. |
| `CONVILYN_HMAC_TOLERANCE_SECONDS` | optional (default 300) | Max clock skew vs the gateway timestamp |
| `CONVILYN_HOST` | optional (default `0.0.0.0`) | uvicorn bind host |
| `CONVILYN_PORT` | optional (default `8080`) | uvicorn bind port |
| `CONVILYN_LOG_LEVEL` | optional (default `INFO`) | Standard Python log level |

## 4. Deployment target — AWS Lambda (Docker image)

Recommended for tool servers with low / bursty traffic. Lambda gives you
free idle (no minutes billed when nothing is calling), automatic scaling,
and a public Function URL with HTTPS already terminated. Cost: $0.20 per
1M requests + compute time.

### 4.1 Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# Install the SDK + your tool server's deps.
COPY pyproject.toml ./
RUN pip install --no-cache-dir convilyn-author
RUN pip install --no-cache-dir -e .  # if you publish your tools as a package

# Copy the server definition.
COPY server.py ./

# Lambda's Python runtime expects a handler module:func — the SDK ships
# an ASGI adapter that routes Lambda events to the uvicorn app.
CMD ["convilyn_author._internal.server_runtime.lambda_handler"]
```

### 4.2 Deploy

```bash
# Build + push to your ECR repository.
docker build -t my-author-server .
aws ecr get-login-password --region us-east-1 | docker login --username AWS \
  --password-stdin <YOUR-ACCOUNT>.dkr.ecr.us-east-1.amazonaws.com
docker tag my-author-server:latest <ECR-URL>:latest
docker push <ECR-URL>:latest

# Create the function (one-time) and enable a Function URL.
aws lambda create-function \
  --function-name my-author-server \
  --package-type Image \
  --code ImageUri=<ECR-URL>:latest \
  --role <YOUR-EXECUTION-ROLE-ARN> \
  --environment "Variables={CONVILYN_HMAC_SECRET=<YOUR-SECRET>}"

aws lambda create-function-url-config \
  --function-name my-author-server \
  --auth-type NONE
```

The Function URL becomes your registration endpoint:

```bash
convilyn-author push --endpoint-url https://<id>.lambda-url.us-east-1.on.aws/
```

### 4.3 Caveats

- **Cold start**: ~600 ms for a fresh container. For latency-sensitive
  tools use Provisioned Concurrency or move to Fargate (Section 5).
- **15-minute timeout**: Lambda hard-stops at 15 min. Long-running tools
  (large LLM batches, video processing) should run async — return a job
  handle, do the work in a separate worker.
- **Function URL is open by default**: Convilyn rejects unsigned bodies,
  so the HMAC check IS your authn. Don't disable it for "dev" with a
  Function URL — anyone can hit it.

## 5. Deployment target — AWS Fargate

Recommended when you need: warm instances (no cold start), > 15 min jobs,
sidecars (vector DB, queue), or VPC-private inbound traffic.

### 5.1 Task definition

```json
{
  "family": "my-author-server",
  "containerDefinitions": [{
    "name": "server",
    "image": "<ECR-URL>:latest",
    "portMappings": [{"containerPort": 8080, "protocol": "tcp"}],
    "environment": [
      {"name": "CONVILYN_HMAC_SECRET", "value": "<SECRET-OR-ARN>"},
      {"name": "CONVILYN_PORT", "value": "8080"}
    ],
    "essential": true
  }],
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024"
}
```

Put the secret in **AWS Secrets Manager** + reference its ARN via
`valueFrom` (NOT inline plaintext). The task's execution role needs
`secretsmanager:GetSecretValue` on that ARN.

### 5.2 Front with an ALB

Fargate tasks aren't directly reachable; terminate HTTPS on an
Application Load Balancer (ACM cert) and target the service. Set the
ALB security group to accept `0.0.0.0/0` on 443 — the HMAC check is
again the authn.

```bash
convilyn-author push --endpoint-url https://my-author-server.example.com/
```

## 6. Deployment target — Plain VM / container

Quickest path for prototyping. Run on any VM with a public IP + a
proxy (Caddy, nginx) terminating HTTPS.

```bash
# On your VM
pip install convilyn-author
export CONVILYN_HMAC_SECRET=<your-secret>
convilyn-author dev --host 0.0.0.0 --port 8080
```

Caddy is the lowest-friction frontend; it auto-issues Let's Encrypt:

```
my-author-server.example.com {
  reverse_proxy localhost:8080
}
```

```bash
convilyn-author push --endpoint-url https://my-author-server.example.com/
```

### 6.1 Caveats

- **Single point of failure**: no auto-scaling, no health-check
  restarts. Fine for prototyping; not production.
- **Long-running**: configure `systemd` (Linux) or a process manager
  (PM2, supervisord) so the server restarts on crash.

## 7. Registering the endpoint

Once your server is reachable + HMAC-secret matches what Convilyn issued
you, register it:

```bash
convilyn-author push \
  --server-file server.py \
  --endpoint-url https://<your-server>/
```

Successful registration:

```
Server submitted: srv_abc123 (pending_verification)
Use 'convilyn-author status' to check verification progress.
```

The platform's verifier then calls your endpoint with a battery of
synthetic requests + the standard MCP tool-discovery probe. Pass that
and your server flips to `active`; you can call it from your own
AI workflows.

## 8. Billing model

Authoring a tool server is **free**. Workflows that *use* your server
spend the caller's quota (their `convilyn` consumer SDK sees
`PlanRequiredError` / `QuotaExceededError` when their plan can't afford
the run — see the consumer SDK's `examples/09_account_quota.py`).

If you publish a tool server publicly via the marketplace, the
caller is billed as usual; publishing gives your tool server
discovery inside the platform.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `convilyn-author push` → 402 | Your developer account lacks Pro tier | Upgrade at <https://convilyn.com/pricing> |
| Inbound calls return 401 | HMAC signature mismatch | Re-issue secret, confirm `CONVILYN_HMAC_SECRET` matches |
| Inbound calls return 408 | Timestamp older than tolerance | Clock skew between your server + Convilyn gateway; sync via NTP |
| `convilyn-author status` shows `verification_failed` | Tool didn't pass synthetic probe | Check logs; common cause is unhandled exception → 500 |

## 10. Managed hosting (preview — not yet generally available)

A managed hosted-runtime is on the roadmap for tool servers that prefer not
to self-host:

```bash
convilyn-author deploy --hosted --region us-east-1   # preview
```

This currently returns `HOSTED_NOT_AVAILABLE` in most accounts (HTTP
503 on current platform builds; older builds answered 501, and
environments with the author-runtime router unmounted answer 404). The
self-hosted targets above (Lambda / Fargate / VM), registered with
`convilyn-author push`, are the supported paths for the beta.
Workflow authoring lives in the Convilyn chat Builder — this SDK is the
tool-server SDK (the `WorkflowSpec` DSL and `submit_workflow` were removed
in 2.3.0b1).
