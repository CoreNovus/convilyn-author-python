"""The ``convilyn_sdk`` → ``convilyn_author`` deprecation alias shim.

Categories: logic / boundary / error / object-state. Warning-emission
tests run the import in a SUBPROCESS so the "first import of the shim"
condition is deterministic regardless of test order; identity tests run
in-process (alias identity is order-independent once imported).
"""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

_SUBPROCESS_SNIPPETS = {
    "warns": (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import convilyn_sdk  # noqa: F401\n"
        "hits = [w for w in caught if issubclass(w.category, DeprecationWarning)]\n"
        "assert len(hits) == 1, f'expected exactly one DeprecationWarning, got {len(hits)}'\n"
        "assert 'convilyn_author' in str(hits[0].message)\n"
    ),
    "old_top_level_is_new": (
        "import convilyn_sdk, convilyn_author\nassert convilyn_sdk is convilyn_author\n"
    ),
    "old_symbols_are_new": (
        "import warnings\n"
        "warnings.simplefilter('ignore')\n"
        "from convilyn_sdk import ToolServer as OldServer\n"
        "from convilyn_author import ToolServer as NewServer\n"
        "assert OldServer is NewServer\n"
    ),
    "submodule_identity": (
        "import warnings\n"
        "warnings.simplefilter('ignore')\n"
        "import convilyn_sdk.server\n"
        "import convilyn_author.server\n"
        "import sys\n"
        "assert sys.modules['convilyn_sdk.server'] is sys.modules['convilyn_author.server']\n"
    ),
    "cli_submodule_identity": (
        "import warnings\n"
        "warnings.simplefilter('ignore')\n"
        "import importlib\n"
        "old = importlib.import_module('convilyn_sdk.cli.main')\n"
        "new = importlib.import_module('convilyn_author.cli.main')\n"
        "assert old is new\n"
    ),
    "missing_submodule_still_errors": (
        "import warnings\n"
        "warnings.simplefilter('ignore')\n"
        "try:\n"
        "    import convilyn_sdk.does_not_exist\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('expected ModuleNotFoundError')\n"
    ),
}


def _run(snippet_key: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SNIPPETS[snippet_key]],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"{snippet_key} failed:\n{proc.stderr}"


# ── logic ─────────────────────────────────────────────────────────────


def test_importing_old_name_emits_exactly_one_deprecation_warning() -> None:
    _run("warns")


def test_old_top_level_module_is_the_new_module() -> None:
    _run("old_top_level_is_new")


def test_public_symbols_are_identical_objects_under_both_names() -> None:
    _run("old_symbols_are_new")


# ── object-state: submodule aliasing keeps a single module instance ──


def test_submodule_import_yields_the_same_module_instance() -> None:
    _run("submodule_identity")


def test_nested_cli_submodule_aliases_to_the_same_instance() -> None:
    _run("cli_submodule_identity")


# ── error: unknown submodules still fail loudly under the alias ──────


def test_missing_submodule_raises_module_not_found() -> None:
    _run("missing_submodule_still_errors")


# ── boundary: in-process alias identity (order-independent) ──────────


def test_in_process_alias_identity() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old = importlib.import_module("convilyn_sdk")
    new = importlib.import_module("convilyn_author")

    assert old is new


def test_in_process_submodule_spec_resolves_via_finder() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        importlib.import_module("convilyn_sdk")
    spec = importlib.util.find_spec("convilyn_sdk.types")

    assert spec is not None


@pytest.mark.parametrize("name", ["ToolServer", "ConvilynClient", "ConvilynManifest"])
def test_smoke_symbols_reachable_under_old_name(name: str) -> None:
    """The sdks.json publish-smoke symbols stay importable via the alias."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old = importlib.import_module("convilyn_sdk")

    assert hasattr(old, name)
