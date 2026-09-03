"""Single source of truth for ``convilyn-author``'s package version.

Read by both:

* ``pyproject.toml`` via ``[tool.hatch.version]`` (so the wheel
  metadata + ``importlib.metadata.version("convilyn-author")`` agree)
* ``convilyn_author.__init__`` for the in-process ``__version__``
  attribute that author code may read at runtime.

Bump this file in CHANGELOG-bumping commits — never edit the
hardcoded constant in two places.
"""

__version__ = "2.4.0b1"
