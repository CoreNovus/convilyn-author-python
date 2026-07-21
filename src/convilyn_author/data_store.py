"""ToolDataStore — data compression layer for tool results.

Large tool outputs are stored and referenced by ``ref_id``. The LLM only
sees ``{ref_id, summary}`` to keep context small. The agent retrieves full
data via the auto-registered ``get_tool_data`` tool when needed.

Mirrors ``mcp_server/mcp-shared/src/mcp_shared/tool_data_store.py``.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataStoreProtocol(Protocol):
    """Interface for storing and retrieving tool data."""

    async def store(self, data: dict[str, Any]) -> str:
        """Store data and return a ref_id."""
        ...

    async def get(self, ref_id: str) -> dict[str, Any] | None:
        """Retrieve data by ref_id, or None if not found."""
        ...


def _generate_ref_id() -> str:
    """Generate a ref_id matching mcp-shared format: ``td_<12-hex>``."""
    return f"td_{os.urandom(6).hex()}"


class InMemoryDataStore:
    """In-memory data store for local development and testing.

    Zero AWS dependencies. Data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def store(self, data: dict[str, Any]) -> str:
        ref_id = _generate_ref_id()
        self._store[ref_id] = {
            "data": data,
            "created_at": int(time.time()),
        }
        return ref_id

    async def get(self, ref_id: str) -> dict[str, Any] | None:
        entry = self._store.get(ref_id)
        if entry is None:
            return None
        return entry["data"]

    @property
    def size(self) -> int:
        return len(self._store)


class DynamoDataStore:
    """DynamoDB-backed data store for production (Lambda) environments.

    Requires ``boto3`` (optional dependency). TTL-based expiration.
    """

    def __init__(
        self,
        table_name: str = "tool-data",
        region: str = "ap-northeast-1",
        endpoint_url: str | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._table_name = table_name
        self._region = region
        self._endpoint_url = endpoint_url
        self._ttl_seconds = ttl_seconds
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            kwargs: dict[str, Any] = {"region_name": self._region}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            self._client = boto3.resource("dynamodb", **kwargs)
        return self._client

    async def store(self, data: dict[str, Any]) -> str:
        ref_id = _generate_ref_id()
        table = self._get_client().Table(self._table_name)
        table.put_item(
            Item={
                "ref_id": ref_id,
                "data": json.dumps(data),
                "ttl": int(time.time()) + self._ttl_seconds,
            }
        )
        return ref_id

    async def get(self, ref_id: str) -> dict[str, Any] | None:
        table = self._get_client().Table(self._table_name)
        response = table.get_item(Key={"ref_id": ref_id})
        item = response.get("Item")
        if item is None:
            return None
        return json.loads(item["data"])


def create_data_store(config: Any) -> DataStoreProtocol:
    """Factory: create the appropriate data store based on config.

    - Local/dev mode → InMemoryDataStore
    - Lambda/production → DynamoDataStore
    """
    if config.is_local:
        return InMemoryDataStore()
    return DynamoDataStore(
        table_name=config.tool_data_table,
        region=config.aws_region,
        endpoint_url=config.dynamodb_endpoint,
    )
