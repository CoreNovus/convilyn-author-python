"""Manifest generation — the compiled blueprint of a ToolServer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from convilyn_author.types import ServerSpec, ToolSpec


class ConvilynManifest(BaseModel):
    """The compiled blueprint of a ToolServer.

    Describes the server's tools and capabilities without running any code.
    The Gateway consumes this to configure routing and agent tool binding.
    """

    sdk_version: str = "1.0.0"
    server: ServerSpec
    tools: list[ToolSpec] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent, exclude_none=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def save(self, path: str | Path = "convilyn.manifest.json") -> Path:
        """Write manifest to a JSON file."""
        out = Path(path)
        out.write_text(self.to_json(), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path = "convilyn.manifest.json") -> ConvilynManifest:
        """Load manifest from a JSON file."""
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate_json(raw)

    @classmethod
    def from_json(cls, data: str) -> ConvilynManifest:
        return cls.model_validate_json(data)
