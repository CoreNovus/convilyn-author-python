"""HMAC request verification for inbound calls from the Convilyn gateway.

Mirrors the gateway's signing logic in ``mcp_gateway/hmac_signer.py``. The
gateway signs every outbound request to developer-hosted tool servers;
this module verifies that signature on the SDK side so a developer's
server rejects forged requests.

Wire format (must match ``mcp_gateway.hmac_signer.sign_request``):

* ``X-Convilyn-Signature``   — HMAC-SHA256 hex digest
* ``X-Convilyn-Timestamp``   — Unix seconds (integer string)
* ``X-Convilyn-Server-Id``   — Server name, audit-only (NOT in signed payload)

Signed payload = ``f"{timestamp}".encode() + b"." + body_bytes``.

The signature uses constant-time comparison; timestamp tolerance defends
against replay (default 300s, configurable via ``CONVILYN_HMAC_TOLERANCE_SECONDS``).
"""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "x-convilyn-signature"
TIMESTAMP_HEADER = "x-convilyn-timestamp"
SERVER_ID_HEADER = "x-convilyn-server-id"


class InvalidSignatureError(Exception):
    """Raised when an inbound HMAC signature fails verification.

    The ``reason`` attribute is a stable machine-readable code; the message
    is human-readable and safe to log. Reasons are intentionally coarse to
    avoid leaking signing details to attackers.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _expected_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = f"{timestamp}".encode() + b"." + body
    return hmac.new(
        secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(
    secret: str,
    body: bytes,
    headers: dict[str, str],
    *,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Verify an inbound HMAC signature; raise on failure.

    Args:
        secret: Shared HMAC secret (must be non-empty).
        body: Raw request body bytes that were signed.
        headers: Request headers, keys lowercased.
        tolerance_seconds: Max clock skew vs gateway in seconds.
        now: Override current time for tests; defaults to ``time.time()``.

    Raises:
        InvalidSignatureError: signature invalid, headers missing, or
            timestamp outside tolerance window.
    """
    if not secret:
        raise InvalidSignatureError(
            "missing_secret",
            "HMAC secret is not configured on the server",
        )

    signature = headers.get(SIGNATURE_HEADER)
    timestamp = headers.get(TIMESTAMP_HEADER)
    if not signature or not timestamp:
        raise InvalidSignatureError(
            "missing_header",
            "Missing X-Convilyn-Signature or X-Convilyn-Timestamp",
        )

    try:
        ts_value = int(timestamp)
    except ValueError as exc:
        raise InvalidSignatureError(
            "invalid_timestamp",
            "X-Convilyn-Timestamp must be an integer Unix-seconds value",
        ) from exc

    current = now if now is not None else time.time()
    if abs(current - ts_value) > tolerance_seconds:
        raise InvalidSignatureError(
            "timestamp_out_of_range",
            "Request timestamp outside acceptable tolerance window",
        )

    expected = _expected_signature(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignatureError(
            "signature_mismatch",
            "Signature did not match expected HMAC-SHA256 digest",
        )
