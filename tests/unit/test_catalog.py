"""Tests for ``convilyn_author.catalog``.

Four categories per the unit-testing skill:
  * logic       — list / describe / search happy paths
  * boundary    — empty catalog, no-colon describe, search-case folding
  * error       — missing catalog file warns and yields empty state
  * object-state — list_* methods return defensive copies (not internal refs)
"""

from __future__ import annotations

import json
from pathlib import Path

from convilyn_author.catalog import ServerInfo, ToolCatalog, ToolInfo


def _write_catalog(tmp_path: Path, *, servers: list[dict]) -> Path:
    """Write a minimal catalog JSON file and return its path."""
    target = tmp_path / "catalog.json"
    target.write_text(
        json.dumps({"servers": servers}),
        encoding="utf-8",
    )
    return target


# ── Loading ────────────────────────────────────────────────────────


class TestToolCatalogLoad:
    def test_loads_servers_and_tools(self, tmp_path: Path) -> None:
        # logic: a populated catalog gets parsed into ServerInfo + ToolInfo
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {
                    "name": "srv-a",
                    "description": "Server A",
                    "capabilities": ["text"],
                    "tools": [
                        {
                            "name": "tool-1",
                            "description": "First tool",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "string"},
                            "capabilities": ["text"],
                        },
                    ],
                },
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert len(catalog.list_servers()) == 1

    def test_server_tool_count_matches_tools(self, tmp_path: Path) -> None:
        # logic: ServerInfo.tool_count equals len(tools)
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {
                    "name": "srv-a",
                    "tools": [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}],
                },
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.list_servers()[0].tool_count == 3

    def test_no_path_yields_empty_catalog(self) -> None:
        # boundary: constructor without a path → empty state
        catalog = ToolCatalog()
        assert catalog.list_servers() == []

    def test_missing_file_yields_empty_catalog(self, tmp_path: Path) -> None:
        # error: missing catalog file should warn but NOT raise
        missing = tmp_path / "nope.json"
        catalog = ToolCatalog(missing)
        assert catalog.list_tools() == []

    def test_tools_default_to_empty_dict_input_schema(self, tmp_path: Path) -> None:
        # boundary: tool entry with no input_schema gets {} default
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {
                    "name": "srv-a",
                    "tools": [{"name": "bare", "description": "no schema"}],
                },
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.list_tools()[0].input_schema == {}


# ── list_* defensive copies ───────────────────────────────────────


class TestToolCatalogListDefensiveCopy:
    def test_list_servers_returns_new_list(self, tmp_path: Path) -> None:
        # object-state: mutating the returned list does not affect internal state
        catalog_path = _write_catalog(tmp_path, servers=[{"name": "srv"}])
        catalog = ToolCatalog(catalog_path)
        catalog.list_servers().clear()
        assert len(catalog.list_servers()) == 1

    def test_list_tools_returns_new_list(self, tmp_path: Path) -> None:
        # object-state: same defensive-copy contract for tools
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv", "tools": [{"name": "t"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        catalog.list_tools().clear()
        assert len(catalog.list_tools()) == 1


# ── list_tools filtering ──────────────────────────────────────────


class TestToolCatalogListTools:
    def test_filters_by_server_name(self, tmp_path: Path) -> None:
        # logic: list_tools(server=X) returns only tools whose server == X
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {"name": "srv-a", "tools": [{"name": "t1"}, {"name": "t2"}]},
                {"name": "srv-b", "tools": [{"name": "t3"}]},
            ],
        )
        catalog = ToolCatalog(catalog_path)
        names = sorted(t.name for t in catalog.list_tools(server="srv-a"))
        assert names == ["t1", "t2"]

    def test_unknown_server_yields_empty_list(self, tmp_path: Path) -> None:
        # boundary: unknown server filter → empty list (not an error)
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv-a", "tools": [{"name": "t"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.list_tools(server="nope") == []


# ── describe ──────────────────────────────────────────────────────


class TestToolCatalogDescribe:
    def test_describes_with_full_qualifier(self, tmp_path: Path) -> None:
        # logic: ``srv:tool`` qualifier returns the matching ToolInfo
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv-a", "tools": [{"name": "tool-1"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        info = catalog.describe("srv-a:tool-1")
        assert isinstance(info, ToolInfo)

    def test_describes_by_bare_name_without_colon(self, tmp_path: Path) -> None:
        # boundary: bare-name input searches across all servers
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv-a", "tools": [{"name": "unique"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        info = catalog.describe("unique")
        assert info is not None and info.name == "unique"

    def test_returns_none_when_qualifier_misses(self, tmp_path: Path) -> None:
        # error: qualified lookup with wrong server returns None
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv-a", "tools": [{"name": "tool-1"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.describe("other-srv:tool-1") is None

    def test_returns_none_when_bare_name_misses(self, tmp_path: Path) -> None:
        # error: bare-name lookup with no match returns None
        catalog_path = _write_catalog(
            tmp_path,
            servers=[{"name": "srv-a", "tools": [{"name": "real"}]}],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.describe("ghost") is None


# ── search ────────────────────────────────────────────────────────


class TestToolCatalogSearch:
    def test_matches_in_name(self, tmp_path: Path) -> None:
        # logic: query found in tool name
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {"name": "srv", "tools": [{"name": "translate", "description": "x"}]},
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert len(catalog.search("trans")) == 1

    def test_matches_in_description(self, tmp_path: Path) -> None:
        # logic: query found in tool description
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {
                    "name": "srv",
                    "tools": [{"name": "x", "description": "Translates strings"}],
                },
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert len(catalog.search("strings")) == 1

    def test_matches_in_capabilities(self, tmp_path: Path) -> None:
        # logic: query matched against capability strings
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {
                    "name": "srv",
                    "tools": [
                        {"name": "x", "description": "y", "capabilities": ["TEXT"]},
                    ],
                },
            ],
        )
        catalog = ToolCatalog(catalog_path)
        # boundary: case-insensitive — uppercase capability matches lowercase query
        assert len(catalog.search("text")) == 1

    def test_search_returns_empty_when_no_match(self, tmp_path: Path) -> None:
        # error: missing query → empty list
        catalog_path = _write_catalog(
            tmp_path,
            servers=[
                {"name": "srv", "tools": [{"name": "x", "description": "y"}]},
            ],
        )
        catalog = ToolCatalog(catalog_path)
        assert catalog.search("nope") == []


# ── Pydantic models ────────────────────────────────────────────────


class TestCatalogModels:
    def test_tool_info_defaults(self) -> None:
        # object-state: ToolInfo defaults — input_schema empty, capabilities empty
        info = ToolInfo(name="t", server="s", description="d")
        assert info.input_schema == {}

    def test_server_info_defaults(self) -> None:
        # object-state: ServerInfo defaults — tool_count 0, capabilities empty
        info = ServerInfo(name="s", description="d")
        assert info.tool_count == 0
