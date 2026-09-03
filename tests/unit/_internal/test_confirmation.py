"""Confirmation-handshake token signing tests.

Four categories per the unit-testing skill:
  * logic        — mint/verify round-trip, own-token self-verification
  * boundary     — expiry edge, volatile presigned-URL param stripping
  * error        — malformed / expired / tampered / wrong-secret tokens
  * object-state — cross-language byte-identical wire format (TS parity)
"""

from __future__ import annotations

import pytest

from convilyn_author._internal.confirmation import (
    ConfirmationInvalidError,
    mint_confirmation_token,
    normalize_for_digest,
    verify_confirmation_token,
)

# ── logic ────────────────────────────────────────────────────────────


class TestMintVerifyRoundTrip:
    def test_a_freshly_minted_token_verifies_against_the_same_arguments(self):
        token = mint_confirmation_token(
            tool_name="delete_resource",
            arguments={"resource_id": "abc123", "force": True},
            expires_at_unix=4102444800,
            secret="s3cr3t",
        )
        verify_confirmation_token(
            tool_name="delete_resource",
            arguments={"resource_id": "abc123", "force": True},
            token=token,
            secret="s3cr3t",
        )  # does not raise

    def test_verification_strips_the_confirmation_token_field_before_hashing(self):
        args = {"resource_id": "abc123"}
        token = mint_confirmation_token(
            tool_name="delete_resource",
            arguments=args,
            expires_at_unix=4102444800,
            secret="s3cr3t",
        )
        # The confirming re-call includes the token alongside the original args.
        verify_confirmation_token(
            tool_name="delete_resource",
            arguments={**args, "confirmation_token": token},
            token=token,
            secret="s3cr3t",
        )  # does not raise


# ── boundary ─────────────────────────────────────────────────────────


class TestExpiryBoundary:
    def test_a_token_at_exactly_its_expiry_instant_is_still_valid(self):
        token = mint_confirmation_token(
            tool_name="t", arguments={}, expires_at_unix=1000, secret="s"
        )
        verify_confirmation_token(
            tool_name="t", arguments={}, token=token, secret="s", now=1000.0
        )  # does not raise

    def test_a_token_one_second_past_expiry_is_rejected(self):
        token = mint_confirmation_token(
            tool_name="t", arguments={}, expires_at_unix=1000, secret="s"
        )
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            verify_confirmation_token(
                tool_name="t", arguments={}, token=token, secret="s", now=1001.0
            )
        assert exc_info.value.reason == "expired"


class TestNormalizeForDigest:
    def test_strips_s3_sigv4_volatile_params_but_keeps_the_rest(self):
        url = (
            "https://bucket.s3.amazonaws.com/key"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef&keep=1"
        )
        normalized = normalize_for_digest({"url": url})
        assert "X-Amz-Algorithm" not in normalized["url"]
        assert "X-Amz-Signature" not in normalized["url"]
        assert "keep=1" in normalized["url"]

    def test_leaves_non_url_strings_untouched(self):
        assert normalize_for_digest({"note": "no query here"}) == {"note": "no query here"}

    def test_recurses_into_nested_lists_and_dicts(self):
        nested = {"files": [{"url": "https://x.example/a?Signature=x&keep=1"}]}
        normalized = normalize_for_digest(nested)
        assert "Signature" not in normalized["files"][0]["url"]
        assert "keep=1" in normalized["files"][0]["url"]


# ── error ────────────────────────────────────────────────────────────


class TestVerificationFailures:
    def test_rejects_a_token_whose_arguments_were_tampered_with(self):
        token = mint_confirmation_token(
            tool_name="t", arguments={"n": 1}, expires_at_unix=4102444800, secret="s"
        )
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            verify_confirmation_token(tool_name="t", arguments={"n": 2}, token=token, secret="s")
        assert exc_info.value.reason == "digest_mismatch"

    def test_rejects_a_token_verified_with_the_wrong_secret(self):
        token = mint_confirmation_token(
            tool_name="t", arguments={}, expires_at_unix=4102444800, secret="right"
        )
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            verify_confirmation_token(tool_name="t", arguments={}, token=token, secret="wrong")
        assert exc_info.value.reason == "signature_mismatch"

    def test_rejects_a_garbage_token(self):
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            verify_confirmation_token(tool_name="t", arguments={}, token="not-base64!!", secret="s")
        assert exc_info.value.reason == "malformed"

    def test_mint_rejects_an_empty_secret(self):
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            mint_confirmation_token(
                tool_name="t", arguments={}, expires_at_unix=4102444800, secret=""
            )
        assert exc_info.value.reason == "malformed"

    def test_verify_rejects_an_empty_secret(self):
        with pytest.raises(ConfirmationInvalidError) as exc_info:
            verify_confirmation_token(tool_name="t", arguments={}, token="x", secret="")
        assert exc_info.value.reason == "malformed"


# ── object-state: cross-language wire-format parity ────────────────────


class TestCrossLanguageByteCompatibility:
    """Locks in the byte-identical result the `test-community` black-box probe
    proved by hand (route F01): a token minted by the real `@convilyn/sdk-author`
    TypeScript implementation must decode/verify identically here, and Python
    minting the same inputs must reproduce the exact same bytes. Turns their
    one-off manual proof into a permanent regression fixture."""

    _SECRET = "cross-lang-shared-secret"
    _TOOL_NAME = "delete_resource"
    _ARGS = {"resource_id": "abc123", "force": True}
    _EXPIRES_AT_UNIX = 4102444800  # 2100-01-01, far future so it never expires

    # Captured verbatim from test-community/logs/f01_mint_ts.log (TOKEN=...),
    # minted by the real @convilyn/sdk-author 0.7.0 mintConfirmationToken().
    _TS_MINTED_TOKEN = (
        "NDEwMjQ0NDgwMDo4Yzg2ZTRkOWRmNzdhNjU5Mzc1Mjk3NWY0NjcwMDZkYzA2M2E5MjM2NGU0MWQ5"
        "MTkyZGMwNTliZDNlYTg5M2QwOjA5NTRmZThhYWQyMmQxZTMxYzAxOGQ0NzI4MWZkMzFmMGRiMDk4"
        "NzUyNjA5MTQwMzMzMmY4OWZiNTE3M2ZjM2I="
    )

    def test_python_verifies_the_ts_minted_token(self):
        verify_confirmation_token(
            tool_name=self._TOOL_NAME,
            arguments=self._ARGS,
            token=self._TS_MINTED_TOKEN,
            secret=self._SECRET,
        )  # does not raise

    def test_python_mints_the_byte_identical_token(self):
        python_minted = mint_confirmation_token(
            tool_name=self._TOOL_NAME,
            arguments=self._ARGS,
            expires_at_unix=self._EXPIRES_AT_UNIX,
            secret=self._SECRET,
        )
        assert python_minted == self._TS_MINTED_TOKEN
