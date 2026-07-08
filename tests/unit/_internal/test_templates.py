"""Template marketplace — logic / boundary / error / object-state.

Network is mocked via ``patch("httpx.get", ...)`` so the suite never
hits PyPI. Subprocess and filesystem are mocked or routed through
``tmp_path`` so the tests never run a real ``pip install`` / ``git clone``
or write to the developer's actual ``~/.convilyn/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from convilyn_sdk._internal import templates
from convilyn_sdk._internal.templates import (
    TemplateEntry,
    TemplateError,
    _validate_suffix,
    catalog_path,
    fetch_template_metadata,
    fork_template,
    install_template,
    list_templates,
    load_catalog,
    save_catalog,
)


class TestValidateSuffix:
    """Suffix validation is anchored with ``\\Z`` (rejects trailing newline)."""

    @pytest.mark.parametrize("name", ["a", "demo", "demo-123", "x9"])
    def test_accepts_valid(self, name: str) -> None:
        _validate_suffix(name)  # does not raise

    @pytest.mark.parametrize(
        "name",
        [
            "name\n",  # trailing newline — $ would have allowed this
            "name\nmalicious",
            "Name",  # uppercase
            "-leading",
            "has space",
            "semi;colon",
            "",
        ],
    )
    def test_rejects_invalid(self, name: str) -> None:
        with pytest.raises(TemplateError) as exc_info:
            _validate_suffix(name)
        assert exc_info.value.code == "INVALID_NAME"


@pytest.fixture
def catalog_in_tmp(tmp_path, monkeypatch) -> Path:
    """Redirect the catalog to a tmp file via the documented env override."""
    path = tmp_path / "templates.json"
    monkeypatch.setenv("CONVILYN_TEMPLATE_CATALOG", str(path))
    return path


def _pypi_simple_payload(*names: str) -> dict:
    return {"projects": [{"name": n} for n in names]}


def _mock_response(
    status_code: int = 200, json_payload: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response

        request = Request("GET", "http://test")
        response = Response(status_code, request=request)
        resp.raise_for_status.side_effect = HTTPStatusError(
            f"HTTP {status_code}", request=request, response=response
        )
    return resp


# ── 1. Logic — list_templates filters by namespace prefix ──────


class TestListLogic:
    def test_returns_only_template_namespaced_names(self) -> None:
        payload = _pypi_simple_payload(
            "convilyn-template-blog",
            "convilyn-template-newsletter",
            "convilyn-author",  # NOT a template
            "django",  # unrelated
        )
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            result = list_templates()
        assert result == [
            "convilyn-template-blog",
            "convilyn-template-newsletter",
        ]

    def test_query_filters_by_suffix_substring(self) -> None:
        payload = _pypi_simple_payload(
            "convilyn-template-blog",
            "convilyn-template-blog-rss",
            "convilyn-template-newsletter",
        )
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            result = list_templates(query="blog")
        assert result == [
            "convilyn-template-blog",
            "convilyn-template-blog-rss",
        ]

    def test_result_is_sorted(self) -> None:
        payload = _pypi_simple_payload(
            "convilyn-template-zeta",
            "convilyn-template-alpha",
        )
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            result = list_templates()
        assert result == [
            "convilyn-template-alpha",
            "convilyn-template-zeta",
        ]


# ── 2. Boundary — empty namespace, malformed rows ──────────────


class TestListBoundary:
    def test_empty_namespace_returns_empty_list(self) -> None:
        payload = _pypi_simple_payload("django", "fastapi")
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            assert list_templates() == []

    def test_skips_non_dict_rows(self) -> None:
        payload = {"projects": [{"name": "convilyn-template-x"}, "garbage", None]}
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            assert list_templates() == ["convilyn-template-x"]


# ── 3. Error — PyPI unavailable / malformed responses ──────────


class TestListErrors:
    def test_network_error_surfaces_with_code(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("boom")):
            with pytest.raises(TemplateError) as exc_info:
                list_templates()
        assert exc_info.value.code == "PYPI_UNAVAILABLE"

    def test_missing_projects_key_rejected(self) -> None:
        with patch(
            "httpx.get", return_value=_mock_response(json_payload={"foo": "bar"})
        ):
            with pytest.raises(TemplateError) as exc_info:
                list_templates()
        assert exc_info.value.code == "PYPI_MALFORMED"


# ── 4. Object-state — TemplateEntry + catalog round-trip ──────


class TestCatalogState:
    def test_catalog_path_honours_env_override(self, tmp_path, monkeypatch) -> None:
        target = tmp_path / "custom.json"
        monkeypatch.setenv("CONVILYN_TEMPLATE_CATALOG", str(target))
        assert catalog_path() == target

    def test_load_returns_empty_when_missing(self, catalog_in_tmp) -> None:
        assert load_catalog() == []

    def test_save_then_load_round_trip(self, catalog_in_tmp) -> None:
        entry = TemplateEntry(
            name="blog",
            package="convilyn-template-blog",
            version="1.2.3",
        )
        save_catalog([entry])
        loaded = load_catalog()
        assert len(loaded) == 1
        assert loaded[0].name == "blog"
        assert loaded[0].version == "1.2.3"

    def test_corrupt_catalog_raises_typed_error(self, catalog_in_tmp) -> None:
        catalog_in_tmp.write_text("not-valid-json", encoding="utf-8")
        with pytest.raises(TemplateError) as exc_info:
            load_catalog()
        assert exc_info.value.code == "CATALOG_CORRUPT"

    def test_non_list_catalog_rejected(self, catalog_in_tmp) -> None:
        catalog_in_tmp.write_text(json.dumps({"oops": True}), encoding="utf-8")
        with pytest.raises(TemplateError) as exc_info:
            load_catalog()
        assert exc_info.value.code == "CATALOG_CORRUPT"


# ── fetch_template_metadata ────────────────────────────────────


class TestFetchMetadata:
    def test_returns_info_block_on_200(self) -> None:
        payload = {
            "info": {"version": "1.0.0", "project_urls": {"Source": "https://x"}}
        }
        with patch("httpx.get", return_value=_mock_response(json_payload=payload)):
            info = fetch_template_metadata("blog")
        assert info["version"] == "1.0.0"

    def test_404_raises_template_not_found(self) -> None:
        with patch("httpx.get", return_value=_mock_response(status_code=404)):
            with pytest.raises(TemplateError) as exc_info:
                fetch_template_metadata("missing")
        assert exc_info.value.code == "TEMPLATE_NOT_FOUND"

    def test_invalid_suffix_rejected(self) -> None:
        with pytest.raises(TemplateError) as exc_info:
            fetch_template_metadata("not safe!")
        assert exc_info.value.code == "INVALID_NAME"


# ── install_template ───────────────────────────────────────────


class TestInstallTemplate:
    def test_success_writes_catalog(self, catalog_in_tmp) -> None:
        pip_ok = MagicMock()
        pip_ok.returncode = 0
        pip_ok.stdout = "Successfully installed"
        pip_ok.stderr = ""

        metadata = _mock_response(
            json_payload={
                "info": {
                    "version": "0.4.2",
                    "project_urls": {"Source": "https://github.com/example/x"},
                }
            }
        )
        with (
            patch(
                "convilyn_sdk._internal.templates.subprocess.run", return_value=pip_ok
            ) as run,
            patch("httpx.get", return_value=metadata),
        ):
            entry = install_template("blog")

        assert entry.name == "blog"
        assert entry.package == "convilyn-template-blog"
        assert entry.version == "0.4.2"
        assert entry.source == "https://github.com/example/x"
        # Catalog was persisted.
        rows = load_catalog()
        assert len(rows) == 1
        # Pip args are pinned (no shell injection surface).
        cmd = run.call_args.args[0]
        assert "convilyn-template-blog" in cmd
        assert "pip" in cmd

    def test_pip_failure_surfaces_pip_failed_code(self, catalog_in_tmp) -> None:
        pip_fail = MagicMock()
        pip_fail.returncode = 1
        pip_fail.stdout = ""
        pip_fail.stderr = "No matching distribution"
        with patch(
            "convilyn_sdk._internal.templates.subprocess.run", return_value=pip_fail
        ):
            with pytest.raises(TemplateError) as exc_info:
                install_template("missing")
        assert exc_info.value.code == "PIP_FAILED"
        # Catalog stays empty when install fails.
        assert load_catalog() == []

    def test_invalid_suffix_short_circuits(self, catalog_in_tmp) -> None:
        with patch("convilyn_sdk._internal.templates.subprocess.run") as run:
            with pytest.raises(TemplateError) as exc_info:
                install_template("../escape")
        assert exc_info.value.code == "INVALID_NAME"
        run.assert_not_called()

    def test_reinstall_replaces_existing_row(self, catalog_in_tmp) -> None:
        save_catalog(
            [
                TemplateEntry(
                    name="blog",
                    package="convilyn-template-blog",
                    version="0.1.0",
                )
            ]
        )
        pip_ok = MagicMock(returncode=0, stdout="", stderr="")
        metadata = _mock_response(
            json_payload={"info": {"version": "0.2.0", "project_urls": {}}}
        )
        with (
            patch(
                "convilyn_sdk._internal.templates.subprocess.run", return_value=pip_ok
            ),
            patch("httpx.get", return_value=metadata),
        ):
            install_template("blog")

        rows = load_catalog()
        assert len(rows) == 1
        assert rows[0].version == "0.2.0"


# ── fork_template ──────────────────────────────────────────────


class TestForkTemplate:
    @pytest.fixture(autouse=True)
    def _public_dns(self):
        """Hermetic DNS: the clone-URL safety gate resolves the host; unit
        tests must never touch the network, so resolution yields a fixed
        public address by default (individual tests re-patch for the
        private-address cases)."""
        import socket as _socket

        addrinfo = [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("140.82.121.4", 0))]
        with patch(
            "convilyn_sdk._internal.urlpolicy.socket.getaddrinfo", return_value=addrinfo
        ):
            yield

    def _metadata_with(self, source: str | None) -> MagicMock:
        info: dict = {"version": "1.0.0", "project_urls": {}}
        if source:
            info["project_urls"]["Source"] = source
        return _mock_response(json_payload={"info": info})

    def test_clone_then_rename(self, tmp_path) -> None:
        """The repo's pyproject + README get rewritten to the new name."""

        def fake_clone(args, **_kwargs):
            # ``git clone --depth 1 <url> <destination>`` — destination is last.
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "pyproject.toml").write_text(
                'name = "convilyn-template-blog"\n', encoding="utf-8"
            )
            (destination / "README.md").write_text(
                "# convilyn-template-blog\n\nA starter.\n", encoding="utf-8"
            )
            (destination / ".git").mkdir()
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "httpx.get",
                return_value=self._metadata_with("https://github.com/x/blog"),
            ),
            patch(
                "convilyn_sdk._internal.templates.subprocess.run",
                side_effect=fake_clone,
            ),
        ):
            destination = fork_template("blog", "my-blog", target_dir=tmp_path)

        assert destination == (tmp_path / "my-blog").resolve()
        assert 'name = "my-blog"' in (destination / "pyproject.toml").read_text()
        assert "my-blog" in (destination / "README.md").read_text()
        # .git/ should have been stripped so the fork starts fresh.
        assert not (destination / ".git").exists()

    def test_missing_source_url_raises(self, tmp_path) -> None:
        with patch("httpx.get", return_value=self._metadata_with(None)):
            with pytest.raises(TemplateError) as exc_info:
                fork_template("blog", "my-blog", target_dir=tmp_path)
        assert exc_info.value.code == "NO_SOURCE_URL"

    def test_destination_exists_raises(self, tmp_path) -> None:
        (tmp_path / "my-blog").mkdir()
        with patch(
            "httpx.get",
            return_value=self._metadata_with("https://github.com/x/blog"),
        ):
            with pytest.raises(TemplateError) as exc_info:
                fork_template("blog", "my-blog", target_dir=tmp_path)
        assert exc_info.value.code == "DESTINATION_EXISTS"

    def test_invalid_new_name_rejected(self, tmp_path) -> None:
        with pytest.raises(TemplateError) as exc_info:
            fork_template("blog", "Bad Name", target_dir=tmp_path)
        assert exc_info.value.code == "INVALID_NAME"

    def test_ssh_url_rejected_as_non_clonable(self, tmp_path) -> None:
        with patch(
            "httpx.get",
            return_value=self._metadata_with("git@github.com:x/blog.git"),
        ):
            with pytest.raises(TemplateError) as exc_info:
                fork_template("blog", "my-blog", target_dir=tmp_path)
        assert exc_info.value.code == "NO_SOURCE_URL"

    def test_git_clone_failure_surfaces(self, tmp_path) -> None:
        clone_fail = MagicMock(returncode=128, stdout="", stderr="repo not found")
        with (
            patch(
                "httpx.get",
                return_value=self._metadata_with("https://github.com/x/blog"),
            ),
            patch(
                "convilyn_sdk._internal.templates.subprocess.run",
                return_value=clone_fail,
            ),
        ):
            with pytest.raises(TemplateError) as exc_info:
                fork_template("blog", "my-blog", target_dir=tmp_path)
        assert exc_info.value.code == "GIT_CLONE_FAILED"


# ── clone-URL policy (allowlist + private-IP gate) ─────────────


class TestCloneUrlPolicy:
    """The clone URL is attacker-writable PyPI metadata — every component
    is validated (host allowlist, userinfo, port, scheme), and the host
    must resolve to a public address before ``git clone`` runs."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/org/repo",
            "https://gitlab.com/org/repo",
            "https://bitbucket.org/org/repo",
            "https://codeberg.org/org/repo",
            "git+https://gitlab.com/org/repo",
            "https://GitHub.com/org/repo",  # host compare is case-insensitive
            "https://github.com./org/repo",  # trailing dot normalised
            "https://github.com:443/org/repo",  # explicit default port ok
        ],
    )
    def test_is_clonable_accepts_allowlisted_https(self, url: str) -> None:
        assert templates._is_clonable(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://169.254.169.254/latest/meta-data",  # metadata IP, not allowlisted
            "https://10.0.0.5/repo.git",  # private IP host
            "https://github.com.evil.com/x",  # suffix attack
            "https://evil-github.com/x",  # lookalike
            # synthetic userinfo fixture (real host is github.com)
            "https://user:pass@github.com/x",  # pragma: allowlist secret
            "https://github.com@evil.com/x",  # real host is evil.com + userinfo
            "https://github.com:8443/x",  # non-443 port
            "http://github.com/x",  # scheme downgrade
            "git@github.com:org/repo",  # SSH
            "https://",  # hostless
            "",
        ],
    )
    def test_is_clonable_rejects_non_allowlisted(self, url: str) -> None:
        assert templates._is_clonable(url) is False

    def test_env_override_extends_allowlist(self, monkeypatch) -> None:
        monkeypatch.setenv(
            templates.ENV_TEMPLATE_CLONE_HOSTS, "git.mycorp.example, other.example"
        )
        assert templates._is_clonable("https://git.mycorp.example/team/repo") is True
        # The default allowlist is widened, never replaced.
        assert templates._is_clonable("https://github.com/org/repo") is True
        monkeypatch.delenv(templates.ENV_TEMPLATE_CLONE_HOSTS)
        assert templates._is_clonable("https://git.mycorp.example/team/repo") is False

    def test_pick_source_url_skips_non_allowlisted_source(self) -> None:
        info = {
            "project_urls": {
                "Source": "https://evil.example/x",
                "Repository": "https://github.com/org/repo",
            }
        }
        assert templates._pick_source_url(info) == "https://github.com/org/repo"

    def test_fork_refuses_private_resolution_before_subprocess(self, tmp_path) -> None:
        """The load-bearing SSRF pin: an allowlisted-looking host that
        resolves to a private address must raise UNSAFE_SOURCE_URL and the
        git subprocess must never be spawned."""
        import socket as _socket

        metadata = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "info": {
                        "version": "1.0.0",
                        "project_urls": {"Source": "https://github.com/org/repo"},
                    }
                }
            ),
        )
        metadata.raise_for_status = MagicMock()
        private = [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
        ]
        with (
            patch("httpx.get", return_value=metadata),
            patch(
                "convilyn_sdk._internal.urlpolicy.socket.getaddrinfo",
                return_value=private,
            ),
            patch("convilyn_sdk._internal.templates.subprocess.run") as run_mock,
        ):
            with pytest.raises(TemplateError) as exc_info:
                templates.fork_template("blog", "my-blog", target_dir=tmp_path)
        assert exc_info.value.code == "UNSAFE_SOURCE_URL"
        run_mock.assert_not_called()

    def test_ensure_safe_clone_url_rejects_non_allowlisted_directly(self) -> None:
        with pytest.raises(TemplateError) as exc_info:
            templates._ensure_safe_clone_url("https://evil.example/repo")
        assert exc_info.value.code == "UNSAFE_SOURCE_URL"
