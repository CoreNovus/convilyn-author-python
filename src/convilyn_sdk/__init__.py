"""Deprecated import alias — ``convilyn_sdk`` is now ``convilyn_author``.

The distribution has always been named ``convilyn-author`` on PyPI; the
import name has been renamed to match (``import convilyn_author``). This
shim keeps ``import convilyn_sdk`` (and every ``convilyn_sdk.<submodule>``
import) working as a pure alias of the new package, with one
``DeprecationWarning`` on first import.

Alias mechanics: this module replaces its own ``sys.modules`` entry with
the real ``convilyn_author`` package and installs a meta-path finder that
resolves any ``convilyn_sdk.<submodule>`` to the ALREADY-IMPORTED
``convilyn_author.<submodule>`` module object — the two names are the
same module instance, so ``isinstance`` checks, module-level state, and
monkeypatching behave identically under either name. No file in the new
package is ever executed twice.

Removal schedule: this shim ships through every remaining 2.x release and
is removed in the next MAJOR (3.0.0) — see CHANGELOG.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import warnings

warnings.warn(
    "The `convilyn_sdk` import name is deprecated; use `import convilyn_author` "
    "instead (the PyPI distribution is unchanged: install `convilyn-author` "
    "with uv or pip). "
    "This alias will be removed in the next major release.",
    DeprecationWarning,
    stacklevel=2,
)

_OLD = "convilyn_sdk"
_NEW = "convilyn_author"


class _AliasLoader(importlib.abc.Loader):
    """Loader that returns the already-imported real module untouched."""

    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):  # real module already executed under _NEW
        pass


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``convilyn_sdk.x.y`` to the ``convilyn_author.x.y`` module."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != _OLD and not fullname.startswith(_OLD + "."):
            return None
        real = importlib.import_module(_NEW + fullname[len(_OLD) :])
        return importlib.util.spec_from_loader(fullname, _AliasLoader(real))


_real = importlib.import_module(_NEW)
if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())
# Make `convilyn_sdk` *be* the new package (attribute access, __path__,
# repr — everything). Submodule imports route through the finder above.
sys.modules[_OLD] = _real
