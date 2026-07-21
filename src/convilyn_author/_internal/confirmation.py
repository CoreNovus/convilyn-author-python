"""Confirmation-handshake token signing — byte-for-byte compatible with the
``mcp-shared`` framework and the Go / TypeScript author SDKs, so a token
minted by a Python-authored server verifies against the gateway (and
vice versa). Port of ``sdk/author-ts/src/confirmation.ts``.

Token wire format: ``base64url("<expires>:<digest>:<sig>")`` (RFC 4648
url-safe, padding kept), where::

    digest = sha256hex(canonical_json(normalize_for_digest(arguments)))
    sig    = hmac_sha256_hex(secret, "<tool_name>|<expires>|<digest>")

This is a **distinct** scheme from the inbound request HMAC in
``convilyn_author._internal.auth`` (which signs ``<timestamp>.<body>``); the two
are not interchangeable.

Byte-exactness notes:

* ``canonical_json`` uses ``json.dumps(sort_keys=True,
  separators=(",", ":"), ensure_ascii=True)`` — Python's own canonical form,
  which the TypeScript SDK hand-reimplements (see ``confirmation.ts``'s
  ``canonicalJson``) to match.
* ``normalize_for_digest`` strips volatile presigned-URL query params before
  hashing (re-encoding kept params with ``quote_plus`` semantics) so a
  re-presigned URL still matches the confirmed arguments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

#: Confirmation token lifetime (seconds); matches the framework constant.
CONFIRMATION_TTL_SECONDS = 300

#: The argument key carrying the token on the confirming re-call (stripped
#: before digest computation).
_CONFIRMATION_FIELD = "confirmation_token"

#: Volatile presigned-URL query params dropped before hashing (matched
#: case-insensitively).
_VOLATILE_SIGNED_URL_PARAMS = {
    # S3 SigV4
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-signature",
    "x-amz-signedheaders",
    "x-amz-security-token",
    # S3 SigV2 (legacy presign)
    "awsaccesskeyid",
    "signature",
    "expires",
    # CloudFront signed URLs
    "key-pair-id",
    "policy",
}

_EXPIRES_PATTERN = re.compile(r"^\d+$")


class ConfirmationInvalidError(Exception):
    """Raised when a confirmation-handshake token fails verification.

    The ``reason`` attribute is a stable machine-readable code (maps to the
    framework's ``CONFIRMATION_INVALID``); the message is human-readable.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _is_url(value: str) -> bool:
    return "://" in value and "?" in value


def _strip_volatile_params(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _VOLATILE_SIGNED_URL_PARAMS
    ]
    new_query = urlencode(kept, quote_via=quote_plus)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def normalize_for_digest(value: Any) -> Any:
    """Recursively drop volatile presign params from any URL strings within `value`."""
    if isinstance(value, list):
        return [normalize_for_digest(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_for_digest(item) for key, item in value.items()}
    if isinstance(value, str) and _is_url(value):
        return _strip_volatile_params(value)
    return value


def _canonical_json(value: Any) -> str:
    """Match TypeScript's ``canonicalJson`` — Python's own ``json.dumps`` IS canonical."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_digest(arguments: dict[str, Any]) -> str:
    canonical = _canonical_json(normalize_for_digest(arguments))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sign(secret: str, tool_name: str, expires: int, digest: str) -> str:
    message = f"{tool_name}|{expires}|{digest}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def mint_confirmation_token(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    expires_at_unix: int,
    secret: str,
) -> str:
    """Mint a confirmation token for a tool call, byte-for-byte compatible
    with the gateway / TypeScript / Go signer."""
    if not secret:
        raise ConfirmationInvalidError("malformed", "confirmation secret is not configured")
    digest = _payload_digest(arguments)
    sig = _sign(secret, tool_name, expires_at_unix, digest)
    raw = f"{expires_at_unix}:{digest}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def verify_confirmation_token(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    token: str,
    secret: str,
    now: float | None = None,
) -> None:
    """Verify a confirmation token against the (re-)supplied arguments.

    Raises ``ConfirmationInvalidError`` on a malformed / expired / mismatched
    token. The ``confirmation_token`` argument (present on the confirming
    re-call) is stripped before re-computing the digest.
    """
    if not secret:
        raise ConfirmationInvalidError("malformed", "confirmation secret is not configured")

    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        expires_str, digest, sig = raw.split(":")
    except Exception as exc:
        raise ConfirmationInvalidError(
            "malformed", "confirmation token could not be decoded"
        ) from exc

    if not _EXPIRES_PATTERN.match(expires_str):
        raise ConfirmationInvalidError("malformed", "confirmation token has a non-integer expiry")
    expires_at_unix = int(expires_str)

    current = now if now is not None else time.time()
    if expires_at_unix < current:
        raise ConfirmationInvalidError("expired", "confirmation token expired")

    stripped = {key: value for key, value in arguments.items() if key != _CONFIRMATION_FIELD}
    expected_digest = _payload_digest(stripped)
    if not hmac.compare_digest(digest, expected_digest):
        raise ConfirmationInvalidError(
            "digest_mismatch", "confirmation token does not match arguments"
        )

    expected_sig = _sign(secret, tool_name, expires_at_unix, digest)
    if not hmac.compare_digest(sig, expected_sig):
        raise ConfirmationInvalidError("signature_mismatch", "confirmation token signature invalid")
