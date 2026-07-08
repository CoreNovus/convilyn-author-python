"""Tests for the DataStore module."""

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from convilyn_sdk.config import SDKConfig
from convilyn_sdk.data_store import (
    DynamoDataStore,
    InMemoryDataStore,
    _generate_ref_id,
    create_data_store,
)


class TestRefIdFormat:
    def test_prefix(self):
        ref_id = _generate_ref_id()
        assert ref_id.startswith("td_")

    def test_length(self):
        ref_id = _generate_ref_id()
        # td_ + 12 hex chars = 15 total
        assert len(ref_id) == 15

    def test_uniqueness(self):
        ids = {_generate_ref_id() for _ in range(100)}
        assert len(ids) == 100


class TestInMemoryDataStore:
    @pytest.mark.asyncio
    async def test_store_returns_ref_id(self):
        store = InMemoryDataStore()
        ref_id = await store.store({"key": "value"})
        assert ref_id.startswith("td_")

    @pytest.mark.asyncio
    async def test_roundtrip(self):
        store = InMemoryDataStore()
        data = {"nested": {"list": [1, 2, 3]}, "text": "hello"}
        ref_id = await store.store(data)
        retrieved = await store.get(ref_id)
        assert retrieved == data

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        store = InMemoryDataStore()
        result = await store.get("td_nonexistent0")
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_stores(self):
        store = InMemoryDataStore()
        id1 = await store.store({"a": 1})
        id2 = await store.store({"b": 2})
        assert id1 != id2
        assert await store.get(id1) == {"a": 1}
        assert await store.get(id2) == {"b": 2}

    @pytest.mark.asyncio
    async def test_size(self):
        store = InMemoryDataStore()
        assert store.size == 0
        await store.store({"x": 1})
        assert store.size == 1
        await store.store({"y": 2})
        assert store.size == 2


class TestCreateDataStore:
    def test_local_config_returns_in_memory(self):
        config = SDKConfig(environment="local")
        store = create_data_store(config)
        assert isinstance(store, InMemoryDataStore)

    def test_localhost_returns_in_memory(self):
        config = SDKConfig(server_host="127.0.0.1")
        store = create_data_store(config)
        assert isinstance(store, InMemoryDataStore)

    def test_non_local_returns_dynamo_store(self, monkeypatch):
        # logic: non-local config + non-loopback host → DynamoDataStore
        # Inject a fake boto3 into sys.modules so _get_client is exercisable
        # without requiring the real optional dependency.
        fake_boto3 = types.ModuleType("boto3")
        fake_boto3.resource = lambda *_a, **_kw: MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        config = SDKConfig(
            environment="production",
            server_host="0.0.0.0",
            tool_data_table="my-table",
            aws_region="us-east-1",
            dynamodb_endpoint="https://dynamo.example.com",
        )
        store = create_data_store(config)
        assert isinstance(store, DynamoDataStore)


# ── DynamoDataStore ────────────────────────────────────────────────


class _FakeTable:
    """Stand-in for a boto3 DynamoDB Table that records calls."""

    def __init__(self, *, get_item_response: dict | None = None) -> None:
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self._get_response = get_item_response or {}

    # boto3's DynamoDB API uses PascalCase keyword arguments (Item, Key) —
    # mimic that exactly so call-site code can be tested verbatim.
    def put_item(self, *, Item: dict) -> None:  # noqa: N803
        self.put_calls.append(Item)

    def get_item(self, *, Key: dict) -> dict:  # noqa: N803
        self.get_calls.append(Key)
        return self._get_response


def _make_dynamo_store_with_table(table: _FakeTable) -> DynamoDataStore:
    """Build a DynamoDataStore whose _get_client returns a fake resource."""
    store = DynamoDataStore(table_name="t", region="us-east-1", ttl_seconds=60)
    fake_resource = MagicMock()
    fake_resource.Table.return_value = table
    # Pre-seed the cached client so boto3 import is never reached
    store._client = fake_resource
    return store


class TestDynamoDataStoreInit:
    def test_constructor_records_table_name(self):
        # logic: constructor stores the table_name verbatim
        store = DynamoDataStore(table_name="my-table")
        assert store._table_name == "my-table"

    def test_constructor_records_region(self):
        # logic: constructor stores the region verbatim
        store = DynamoDataStore(region="eu-west-1")
        assert store._region == "eu-west-1"

    def test_constructor_records_endpoint_url(self):
        # logic: optional endpoint_url is recorded for LocalStack-style overrides
        store = DynamoDataStore(endpoint_url="https://dynamo.test")
        assert store._endpoint_url == "https://dynamo.test"

    def test_constructor_records_ttl(self):
        # logic: ttl_seconds is recorded
        store = DynamoDataStore(ttl_seconds=7200)
        assert store._ttl_seconds == 7200

    def test_client_is_lazy_initialized_none(self):
        # object-state: _client is None until _get_client is first called
        store = DynamoDataStore()
        assert store._client is None


class TestDynamoDataStoreGetClient:
    def test_get_client_caches_the_resource(self, monkeypatch):
        # object-state: a second call reuses the cached client (no re-import)
        fake_boto3 = types.ModuleType("boto3")
        sentinel_resource = object()
        fake_boto3.resource = lambda *_a, **_kw: sentinel_resource  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        store = DynamoDataStore()
        first = store._get_client()
        second = store._get_client()
        assert first is second

    def test_get_client_passes_endpoint_url_when_set(self, monkeypatch):
        # logic: endpoint_url, when set, is forwarded to boto3.resource as a kwarg
        fake_boto3 = types.ModuleType("boto3")
        captured: dict[str, object] = {}

        def fake_resource(name: str, **kwargs: object) -> object:
            captured["name"] = name
            captured.update(kwargs)
            return object()

        fake_boto3.resource = fake_resource  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        store = DynamoDataStore(endpoint_url="https://dynamo.test")
        store._get_client()
        assert captured.get("endpoint_url") == "https://dynamo.test"

    def test_get_client_omits_endpoint_url_when_unset(self, monkeypatch):
        # boundary: no endpoint_url → kwarg not passed to boto3.resource
        fake_boto3 = types.ModuleType("boto3")
        captured_kwargs: dict[str, object] = {}

        def fake_resource(name: str, **kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return object()

        fake_boto3.resource = fake_resource  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        store = DynamoDataStore(endpoint_url=None)
        store._get_client()
        assert "endpoint_url" not in captured_kwargs


class TestDynamoDataStoreStore:
    @pytest.mark.asyncio
    async def test_store_returns_ref_id_with_prefix(self):
        # logic: store() generates and returns a td_-prefixed ref_id
        table = _FakeTable()
        store = _make_dynamo_store_with_table(table)
        ref_id = await store.store({"a": 1})
        assert ref_id.startswith("td_")

    @pytest.mark.asyncio
    async def test_store_persists_data_as_json_under_ref_id(self):
        # logic: the put_item Item dict contains data as a JSON string
        table = _FakeTable()
        store = _make_dynamo_store_with_table(table)
        ref_id = await store.store({"a": 1, "b": [1, 2]})
        item = table.put_calls[0]
        assert json.loads(item["data"]) == {"a": 1, "b": [1, 2]}
        assert item["ref_id"] == ref_id


class TestDynamoDataStoreGet:
    @pytest.mark.asyncio
    async def test_get_returns_decoded_data_when_item_present(self):
        # logic: get() decodes the stored JSON payload
        table = _FakeTable(
            get_item_response={"Item": {"ref_id": "td_x", "data": '{"k": "v"}'}},
        )
        store = _make_dynamo_store_with_table(table)
        assert await store.get("td_x") == {"k": "v"}

    @pytest.mark.asyncio
    async def test_get_returns_none_when_item_missing(self):
        # error: missing item in DynamoDB → None (no exception)
        table = _FakeTable(get_item_response={})  # No "Item" key
        store = _make_dynamo_store_with_table(table)
        assert await store.get("td_missing") is None
