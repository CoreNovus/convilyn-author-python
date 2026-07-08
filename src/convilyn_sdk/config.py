"""SDK configuration from environment variables.

Supports both local development (network isolation) and platform
API access (API key authentication) modes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SDKConfig:
    """Configuration for the Convilyn SDK, loaded from environment variables."""

    server_host: str = "127.0.0.1"
    server_port: int = 8080
    log_level: str = "INFO"
    aws_region: str = "ap-northeast-1"
    dynamodb_endpoint: str | None = None
    tool_data_table: str = "tool-data"
    environment: str = "local"
    api_key: str | None = None
    platform_url: str = "https://api.convilyn.corenovus.com"
    hmac_secret: str | None = None
    hmac_tolerance_seconds: int = 300

    @property
    def is_lambda(self) -> bool:
        """Check if running inside AWS Lambda."""
        return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

    @property
    def is_local(self) -> bool:
        """Check if running in local development mode.

        Used ONLY to pick the data store (InMemory vs DynamoDB). This is
        deliberately NOT an authentication signal — inbound ``/mcp``
        signature verification is fail-closed and gated on an explicit
        opt-in (``ToolServer.run(dev=True)`` / ``CONVILYN_DEV_INSECURE``),
        never on this heuristic. See ``_internal.server_runtime``.
        """
        return self.environment == "local" or (
            not self.is_lambda and self.server_host in ("127.0.0.1", "localhost")
        )

    @classmethod
    def from_env(cls) -> SDKConfig:
        return cls(
            server_host=os.environ.get("CONVILYN_HOST", "127.0.0.1"),
            server_port=int(os.environ.get("CONVILYN_PORT", "8080")),
            log_level=os.environ.get("CONVILYN_LOG_LEVEL", "INFO"),
            aws_region=os.environ.get("AWS_REGION", "ap-northeast-1"),
            dynamodb_endpoint=os.environ.get("DYNAMODB_ENDPOINT"),
            tool_data_table=os.environ.get("TOOL_DATA_TABLE", "tool-data"),
            environment=os.environ.get("CONVILYN_ENVIRONMENT", "local"),
            api_key=os.environ.get("CONVILYN_API_KEY"),
            platform_url=os.environ.get(
                "CONVILYN_PLATFORM_URL", "https://api.convilyn.corenovus.com"
            ),
            hmac_secret=os.environ.get("CONVILYN_HMAC_SECRET") or None,
            hmac_tolerance_seconds=int(
                os.environ.get("CONVILYN_HMAC_TOLERANCE_SECONDS", "300")
            ),
        )
