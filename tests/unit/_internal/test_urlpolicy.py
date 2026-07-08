"""Unit tests for the vendored SSRF L1 policy (`_internal/urlpolicy.py`).

Hermetic — ``socket.getaddrinfo`` is monkeypatched in every resolution
test; no real DNS is performed. Categories: logic / boundary / error.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from convilyn_sdk._internal import urlpolicy


def _addrinfo(*ips: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


# ── private-network table (boundary) ─────────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "0.0.0.1",  # "this" network
        "10.1.2.3",  # RFC1918
        "100.64.0.1",  # CGNAT
        "127.0.0.1",  # loopback
        "169.254.169.254",  # link-local / AWS metadata
        "172.16.0.1",  # RFC1918
        "192.0.2.10",  # TEST-NET-1
        "192.168.1.1",  # RFC1918
        "198.18.0.1",  # benchmarking
        "203.0.113.9",  # TEST-NET-3
        "224.0.0.1",  # multicast
        "240.0.0.1",  # class E
        "::1",  # IPv6 loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "64:ff9b::a00:1",  # NAT64-embedded private
        "fc00::1",  # unique local
        "fe80::1",  # IPv6 link-local
    ],
)
def test_url_resolving_to_private_ip_is_unsafe(ip: str) -> None:
    with patch.object(urlpolicy.socket, "getaddrinfo", return_value=_addrinfo(ip)):
        assert urlpolicy.is_safe_url("https://template-host.example/repo") is False


def test_url_resolving_to_public_ip_is_safe() -> None:
    with patch.object(
        urlpolicy.socket, "getaddrinfo", return_value=_addrinfo("140.82.121.4")
    ):
        assert urlpolicy.is_safe_url("https://github.com/org/repo") is True


def test_any_one_private_address_among_many_rejects() -> None:
    mixed = _addrinfo("140.82.121.4", "10.0.0.5")
    with patch.object(urlpolicy.socket, "getaddrinfo", return_value=mixed):
        assert urlpolicy.is_safe_url("https://rebinder.example/x") is False


# ── blocked suffixes + resolution failures (error) ───────────────


@pytest.mark.parametrize(
    "host", ["gateway.internal", "printer.local", "db.cluster.local", "api.svc"]
)
def test_blocked_suffix_is_unsafe_without_resolving(host: str) -> None:
    with patch.object(
        urlpolicy.socket, "getaddrinfo", side_effect=AssertionError("must not resolve")
    ):
        assert urlpolicy.is_safe_url(f"https://{host}/x") is False


def test_dns_failure_is_unsafe() -> None:
    with patch.object(
        urlpolicy.socket, "getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")
    ):
        assert urlpolicy.is_safe_url("https://does-not-exist.example/x") is False


def test_hostless_url_is_unsafe() -> None:
    assert urlpolicy.is_safe_url("not a url") is False
    assert urlpolicy.is_safe_url("file:///etc/passwd") is False


def test_empty_resolution_is_unsafe() -> None:
    with patch.object(urlpolicy.socket, "getaddrinfo", return_value=[]):
        assert urlpolicy.is_safe_url("https://empty.example/x") is False
