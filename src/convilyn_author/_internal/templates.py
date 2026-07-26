"""Template marketplace — PyPI discovery + install + fork.

The marketplace lives under the
``convilyn-template-*`` namespace on PyPI:

* :func:`list_templates` queries the PyPI simple index and filters by
  the namespace prefix.
* :func:`install_template` shells out to ``pip install
  convilyn-template-<name>`` and records the install in the per-user
  catalog at ``~/.convilyn/templates.json``.
* :func:`fork_template` reads the template's PyPI metadata for the
  source-repo URL, ``git clone`` s it under the new name, and rewrites
  ``pyproject.toml`` + README to use the forked identity.

It complements the in-app community marketplace (for end-user
discovery inside the Convilyn web app); this surface is for **author**
workflows where Git + IDE
ergonomics matter more than a curated UI.

The whole module is import-safe: it pulls httpx only when a function
that actually hits PyPI runs, so ``convilyn-author --help`` doesn't
pay the import cost.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from convilyn_author._internal import urlpolicy

#: Every published template package name starts with this prefix.
TEMPLATE_PREFIX: str = "convilyn-template-"

#: PyPI JSON-form simple index. Returns ``{"projects": [{"name": "..."}, ...]}``.
PYPI_SIMPLE_URL: str = "https://pypi.org/simple/"

#: PyPI per-package JSON metadata URL. ``{package}`` is the full name
#: including the namespace prefix.
PYPI_JSON_URL_TEMPLATE: str = "https://pypi.org/pypi/{package}/json"

#: Names that are valid as both PyPI package suffixes and project dir
#: names — same rule pip applies. Keeps the install/fork path safe
#: against shell injection. Anchored with ``\Z`` (not ``$``) so a value
#: with a trailing newline (``"name\n"``) is rejected — ``$`` matches
#: before a trailing newline and would let it through.
_VALID_SUFFIX: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")

#: Hosts a template's source repo may be cloned from. The clone URL comes
#: from the template package's PyPI ``project_urls`` — attacker-writable
#: by anyone who publishes a ``convilyn-template-*`` package — so this is
#: a default-deny, EXACT-match allowlist (no suffix matching:
#: ``github.com.evil.com`` does not pass).
_ALLOWED_CLONE_HOSTS: frozenset[str] = frozenset(
    {"github.com", "gitlab.com", "bitbucket.org", "codeberg.org"}
)

#: Operator escape hatch for self-hosted git: a comma-separated list of
#: additional exact hostnames. An explicit env var set by the operator is
#: their own trust decision — it never widens the default.
ENV_TEMPLATE_CLONE_HOSTS: str = "CONVILYN_TEMPLATE_CLONE_HOSTS"


def _allowed_clone_hosts() -> frozenset[str]:
    extra = os.environ.get(ENV_TEMPLATE_CLONE_HOSTS, "")
    hosts = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return _ALLOWED_CLONE_HOSTS | frozenset(hosts)


class TemplateError(Exception):
    """Raised when a template-marketplace operation fails.

    Carries an optional ``code`` so the CLI can branch on common
    failure modes (network failure, name conflict, missing repo URL)
    without parsing the message.
    """

    def __init__(self, message: str, *, code: str = "TEMPLATE_ERROR") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TemplateEntry:
    """One row in the local install catalog.

    Names follow the PyPI shape: ``package`` is the full package name
    (``convilyn-template-<suffix>``), ``name`` is just the suffix that
    the CLI accepts as a verb argument.
    """

    name: str
    package: str
    version: str
    installed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    source: str | None = None


# ── Catalog ─────────────────────────────────────────────────────


def catalog_path() -> Path:
    """Resolve the catalog file path.

    Defaults to ``~/.convilyn/templates.json``; tests + CI override
    via the ``CONVILYN_TEMPLATE_CATALOG`` env var so they never write
    to the developer's real home directory.
    """
    override = os.environ.get("CONVILYN_TEMPLATE_CATALOG")
    if override:
        return Path(override)
    return Path.home() / ".convilyn" / "templates.json"


def load_catalog() -> list[TemplateEntry]:
    """Read the per-user catalog. Empty list when the file is missing."""
    path = catalog_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateError(
            f"Catalog at {path} is not valid JSON — delete it to reset: {exc}",
            code="CATALOG_CORRUPT",
        ) from exc
    if not isinstance(raw, list):
        raise TemplateError(
            f"Catalog at {path} must be a JSON list of entries",
            code="CATALOG_CORRUPT",
        )
    return [TemplateEntry(**row) for row in raw]


def save_catalog(entries: list[TemplateEntry]) -> None:
    """Persist the catalog atomically; creates the parent dir as needed."""
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    serialised = [entry.__dict__ for entry in entries]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(serialised, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _upsert_catalog(entry: TemplateEntry) -> None:
    """Insert ``entry`` into the catalog, replacing any existing row of
    the same ``name`` (so reinstall doesn't grow the file unbounded)."""
    entries = [e for e in load_catalog() if e.name != entry.name]
    entries.append(entry)
    save_catalog(entries)


# ── Discovery ───────────────────────────────────────────────────


def list_templates(*, query: str | None = None) -> list[str]:
    """Return PyPI package names under the ``convilyn-template-`` namespace.

    Args:
        query: Optional case-insensitive substring filter applied to the
            *suffix* (the part after ``convilyn-template-``).

    Returns:
        Sorted list of full package names. Empty list when nothing
        matches — the namespace is brand-new in R9, so an empty
        result is the steady state until authors start publishing.

    Raises:
        TemplateError: PyPI unreachable or returned an unexpected shape.
    """
    import httpx

    try:
        response = httpx.get(
            PYPI_SIMPLE_URL,
            headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise TemplateError(f"PyPI listing unavailable: {exc}", code="PYPI_UNAVAILABLE") from exc
    except json.JSONDecodeError as exc:
        raise TemplateError(
            f"PyPI returned a malformed JSON index: {exc}",
            code="PYPI_MALFORMED",
        ) from exc

    projects = payload.get("projects") if isinstance(payload, dict) else None
    if not isinstance(projects, list):
        raise TemplateError(
            "PyPI simple index missing the 'projects' array",
            code="PYPI_MALFORMED",
        )

    matches: list[str] = []
    needle = query.lower() if query else None
    for row in projects:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.startswith(TEMPLATE_PREFIX):
            continue
        if needle is not None and needle not in name[len(TEMPLATE_PREFIX) :].lower():
            continue
        matches.append(name)
    return sorted(matches)


def fetch_template_metadata(suffix: str) -> dict[str, Any]:
    """Return the ``info`` block from PyPI's JSON metadata for the package.

    Raises:
        TemplateError: package not on PyPI, network failure, or bad
            JSON shape. The CLI surfaces this as a clean "template not
            found" message.
    """
    _validate_suffix(suffix)
    import httpx

    package = f"{TEMPLATE_PREFIX}{suffix}"
    url = PYPI_JSON_URL_TEMPLATE.format(package=package)
    try:
        response = httpx.get(url, timeout=30.0)
    except httpx.HTTPError as exc:
        raise TemplateError(
            f"PyPI metadata for {package!r} unavailable: {exc}",
            code="PYPI_UNAVAILABLE",
        ) from exc
    if response.status_code == 404:
        raise TemplateError(
            f"No PyPI package named {package!r}",
            code="TEMPLATE_NOT_FOUND",
        )
    response.raise_for_status()
    payload = response.json()
    info = payload.get("info") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        raise TemplateError(
            f"PyPI JSON for {package!r} missing 'info' block",
            code="PYPI_MALFORMED",
        )
    return info


# ── Install ─────────────────────────────────────────────────────


def install_template(suffix: str) -> TemplateEntry:
    """Install ``convilyn-template-<suffix>`` via pip and record it.

    Returns the catalog row that was written. Re-installing the same
    template overwrites the prior row (no duplicate accumulation).

    Raises:
        TemplateError: invalid suffix, pip failure, or metadata lookup
            failure. The catalog is left untouched on failure.
    """
    _validate_suffix(suffix)
    package = f"{TEMPLATE_PREFIX}{suffix}"

    completed = subprocess.run(  # noqa: S603 - inputs validated, args list is closed
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise TemplateError(
            f"pip install {package!r} failed (exit {completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()}",
            code="PIP_FAILED",
        )

    info = fetch_template_metadata(suffix)
    entry = TemplateEntry(
        name=suffix,
        package=package,
        version=str(info.get("version", "0.0.0")),
        source=_pick_source_url(info),
    )
    _upsert_catalog(entry)
    return entry


# ── Fork ────────────────────────────────────────────────────────


def fork_template(suffix: str, new_name: str, *, target_dir: Path | None = None) -> Path:
    """Clone the template's source repo and rewrite it under ``new_name``.

    The fork is created under the caller's current working directory
    (or ``target_dir`` when supplied) as a sibling folder named
    ``new_name``. The ``.git/`` directory is removed so the fork
    starts with a clean history; the original ``pyproject.toml``
    ``name`` field is rewritten and any README reference to the old
    PyPI name is replaced.

    Args:
        suffix: Source template suffix (the part after
            ``convilyn-template-``).
        new_name: Destination project name; must match
            ``^[a-z0-9][a-z0-9-]*$`` (same validation as a PyPI name).
        target_dir: Parent directory under which to create the fork.
            Defaults to the current working directory.

    Returns:
        Path to the created fork directory.

    Raises:
        TemplateError: source URL missing on PyPI metadata, destination
            already exists, ``git clone`` failure, or invalid name.
    """
    _validate_suffix(suffix)
    _validate_suffix(new_name)

    info = fetch_template_metadata(suffix)
    source_url = _pick_source_url(info)
    if not source_url:
        raise TemplateError(
            f"PyPI metadata for {TEMPLATE_PREFIX}{suffix}: no source URL "
            "exposed. Add a 'Source' or 'Repository' entry under "
            "project_urls to enable fork.",
            code="NO_SOURCE_URL",
        )

    base = (target_dir or Path.cwd()).resolve()
    destination = base / new_name
    if destination.exists():
        raise TemplateError(
            f"Destination {destination} already exists",
            code="DESTINATION_EXISTS",
        )

    # Final gate: allowlisted https host + public-address resolution. The
    # URL is attacker-writable PyPI metadata; this must fire BEFORE the
    # subprocess (see _ensure_safe_clone_url for the L2/TOCTOU rationale).
    _ensure_safe_clone_url(source_url)

    clone = subprocess.run(  # noqa: S603 - args list is closed; URL passed _ensure_safe_clone_url
        ["git", "clone", "--depth", "1", source_url, str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise TemplateError(
            f"git clone {source_url!r} failed (exit {clone.returncode}): "
            f"{(clone.stderr or clone.stdout).strip()}",
            code="GIT_CLONE_FAILED",
        )

    _rename_in_place(destination, old=f"{TEMPLATE_PREFIX}{suffix}", new=new_name)
    git_dir = destination / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir, ignore_errors=True)
    return destination


# ── Helpers ─────────────────────────────────────────────────────


def _validate_suffix(suffix: str) -> None:
    """Reject anything that wouldn't be a valid PyPI suffix / dir name.

    Pre-empts shell injection (the values flow into ``pip install`` and
    ``git clone`` argv lists) and catches typos before they hit the
    network.
    """
    if not isinstance(suffix, str) or not _VALID_SUFFIX.match(suffix):
        raise TemplateError(
            f"Invalid template name {suffix!r}: must match {_VALID_SUFFIX.pattern}",
            code="INVALID_NAME",
        )


def _pick_source_url(info: dict[str, Any]) -> str | None:
    """Pick the best git-clonable URL from a PyPI ``info`` dict.

    Order: ``project_urls.Source`` → ``Repository`` → ``Code`` →
    ``home_page``. Only schemes ``https://`` and ``git+https://`` are
    accepted — ``git@`` SSH URLs need credentials the SDK can't
    assume.
    """
    project_urls = info.get("project_urls") or {}
    if isinstance(project_urls, dict):
        for key in ("Source", "source", "Repository", "repository", "Code"):
            url = project_urls.get(key)
            if isinstance(url, str) and _is_clonable(url):
                return url
    home_page = info.get("home_page")
    if isinstance(home_page, str) and _is_clonable(home_page):
        return home_page
    return None


def _is_clonable(url: str) -> bool:
    """True only for https URLs on an allowlisted git host.

    The URL is attacker-writable PyPI metadata, so every component is
    checked, not just the scheme prefix:

    - scheme must be exactly ``https`` (after stripping an optional
      ``git+`` prefix) — no SSH, no schemeless paths;
    - hostname must EXACTLY match the clone-host allowlist (lowercased,
      trailing dot stripped) — kills ``github.com.evil.com``;
    - userinfo is rejected — kills ``https://github.com@evil.com/…``
      credential-confusion (the real host there is ``evil.com``);
    - an explicit non-443 port is rejected.
    """
    candidate = url.removeprefix("git+")
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is not None and port != 443:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return bool(hostname) and hostname in _allowed_clone_hosts()


def _ensure_safe_clone_url(url: str) -> None:
    """Final gate before ``git clone`` — allowlist + private-IP resolution.

    Re-runs :func:`_is_clonable` (defence-in-depth if a future caller
    skips ``_pick_source_url``) and then applies the vendored SSRF L1
    policy: resolve the hostname and reject if any address is private
    (169.254.0.0/16 metadata, RFC1918, loopback, IPv6 ULA/link-local, …).

    L2 IP-pinning is deliberately NOT applied: ``git`` is a subprocess
    doing its own DNS/TLS, so there is no transport to pin. The accepted
    residual is the resolve→clone TOCTOU window, mitigated by the exact
    host allowlist (the attacker would have to rebind DNS for github.com
    itself) plus git's TLS certificate validation of the allowlisted
    hostname (a rebound private IP cannot present a valid cert).
    """
    if not _is_clonable(url):
        raise TemplateError(
            f"Refusing to clone {url!r}: not an https URL on an allowed "
            f"git host ({', '.join(sorted(_allowed_clone_hosts()))}). "
            f"Self-hosted git can be allowed via {ENV_TEMPLATE_CLONE_HOSTS}.",
            code="UNSAFE_SOURCE_URL",
        )
    if not urlpolicy.is_safe_url(url.removeprefix("git+")):
        raise TemplateError(
            f"Refusing to clone {url!r}: host does not resolve to a public "
            "address (private/link-local/metadata ranges are blocked).",
            code="UNSAFE_SOURCE_URL",
        )


def _rename_in_place(root: Path, *, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` in pyproject.toml + README files.

    Conservative — only touches files at the project root + the
    top-level README family. Deeper rewrites (Python module paths,
    etc.) are the caller's responsibility because they often involve
    judgement calls a regex can't make.
    """
    targets = ["pyproject.toml", "README.md", "README.rst", "README.txt"]
    for name in targets:
        path = root / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
