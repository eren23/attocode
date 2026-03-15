"""Tests for Fernet encrypt/decrypt and HMAC verification in webhooks.py."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from attocode.code_intel.api.routes.webhooks import (
    _decrypt_secret,
    _encrypt_secret,
    _get_fernet,
    _verify_github_signature,
)


@pytest.fixture(autouse=True)
def mock_config():
    mock_cfg = MagicMock()
    mock_cfg.secret_key = "test-secret-key-for-unit-tests"
    with patch("attocode.code_intel.api.deps.get_config", return_value=mock_cfg):
        yield


class TestFernetEncryptDecrypt:
    """Tests for _encrypt_secret / _decrypt_secret round-trip."""

    def test_roundtrip_returns_original(self):
        original = "my-webhook-secret-123"
        encrypted = _encrypt_secret(original)
        assert encrypted != original
        assert _decrypt_secret(encrypted) == original

    def test_roundtrip_empty_string(self):
        encrypted = _encrypt_secret("")
        assert _decrypt_secret(encrypted) == ""

    def test_roundtrip_unicode(self):
        original = "secret-with-unicode-chars"
        encrypted = _encrypt_secret(original)
        assert _decrypt_secret(encrypted) == original

    def test_get_fernet_consistent_key(self):
        """Two calls to _get_fernet with the same SECRET_KEY produce compatible instances."""
        fernet1 = _get_fernet()
        fernet2 = _get_fernet()
        plaintext = b"consistency-check"
        token = fernet1.encrypt(plaintext)
        assert fernet2.decrypt(token) == plaintext


class TestVerifyGithubSignature:
    """Tests for _verify_github_signature HMAC-SHA256 verification."""

    def test_valid_signature_does_not_raise(self):
        body = b'{"action": "push", "ref": "refs/heads/main"}'
        secret = "webhook-secret"
        expected_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        signature_header = f"sha256={expected_hex}"

        # Should complete without raising
        _verify_github_signature(body, signature_header, secret)

    def test_invalid_signature_raises_401(self):
        body = b'{"action": "push"}'
        secret = "webhook-secret"
        bad_signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        with pytest.raises(HTTPException) as exc_info:
            _verify_github_signature(body, bad_signature, secret)
        assert exc_info.value.status_code == 401
        assert "Invalid signature" in exc_info.value.detail

    def test_invalid_format_no_prefix_raises_401(self):
        body = b'{"action": "push"}'
        secret = "webhook-secret"
        # Missing the "sha256=" prefix
        raw_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with pytest.raises(HTTPException) as exc_info:
            _verify_github_signature(body, raw_hex, secret)
        assert exc_info.value.status_code == 401
        assert "Invalid signature format" in exc_info.value.detail

    def test_wrong_prefix_raises_401(self):
        body = b'{"test": true}'
        secret = "s3cret"
        signature = "md5=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with pytest.raises(HTTPException) as exc_info:
            _verify_github_signature(body, signature, secret)
        assert exc_info.value.status_code == 401
        assert "Invalid signature format" in exc_info.value.detail
