"""Tests for remote-mode graceful degradation.

When the configured remote is unusable — an expired JWT or an unreachable
server — code-intel must NOT hard-fail. It should leave ``_remote_service``
unset (so every tool transparently runs against the local engine) and record
a human-readable reason. These tests pin that behaviour.
"""

from __future__ import annotations

import base64
import json

import httpx
import respx

import attocode.code_intel._shared as shared
from attocode.code_intel.api.providers.remote_provider import RemoteTextService
from attocode.code_intel.config import token_is_expired

SERVER = "https://ci.example.com"
REPO_ID = "repo-abc-123"


def _b64url(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


def _make_jwt(payload: dict) -> str:
    """Build a syntactically-valid JWT (signature is not checked by the gate)."""
    return f"{_b64url({'alg': 'HS256', 'typ': 'JWT'})}.{_b64url(payload)}.sig"


_EXPIRED = _make_jwt({"exp": 1_000_000_000})  # 2001-09-09
_FUTURE = _make_jwt({"exp": 9_999_999_999})  # 2286-11-20


# ---------------------------------------------------------------------------
# token_is_expired — decodes the exp claim WITHOUT verifying the signature
# (we don't hold the remote server's signing key).
# ---------------------------------------------------------------------------


class TestTokenIsExpired:
    def test_past_exp_is_expired(self):
        assert token_is_expired(_EXPIRED) is True

    def test_future_exp_not_expired(self):
        assert token_is_expired(_FUTURE) is False

    def test_no_exp_claim_not_expired(self):
        # Can't prove expiry without an exp claim — let the health check decide.
        assert token_is_expired(_make_jwt({"sub": "u"})) is False

    def test_garbage_not_expired(self):
        assert token_is_expired("not-a-jwt") is False
        assert token_is_expired("only.two") is False
        assert token_is_expired("") is False


# ---------------------------------------------------------------------------
# RemoteTextService.ping — best-effort reachability probe
# ---------------------------------------------------------------------------


class TestRemotePing:
    def test_ping_true_when_reachable(self):
        with respx.mock:
            respx.get(f"{SERVER}/health").mock(return_value=httpx.Response(200, json={}))
            svc = RemoteTextService(SERVER, "tok", REPO_ID)
            try:
                assert svc.ping() is True
            finally:
                svc.close()

    def test_ping_false_on_connection_error(self):
        with respx.mock:
            respx.get(f"{SERVER}/health").mock(side_effect=httpx.ConnectError("refused"))
            svc = RemoteTextService(SERVER, "tok", REPO_ID)
            try:
                assert svc.ping() is False
            finally:
                svc.close()

    def test_ping_false_on_server_error(self):
        with respx.mock:
            respx.get(f"{SERVER}/health").mock(return_value=httpx.Response(503))
            svc = RemoteTextService(SERVER, "tok", REPO_ID)
            try:
                assert svc.ping() is False
            finally:
                svc.close()


# ---------------------------------------------------------------------------
# configure_remote_service — gate on expiry + reachability, fall back to local
# ---------------------------------------------------------------------------


class TestConfigureRemoteGraceful:
    def teardown_method(self):
        shared.clear_remote_service()

    def test_skips_remote_when_token_expired(self):
        shared.clear_remote_service()
        shared.configure_remote_service("http://127.0.0.1:8080", _EXPIRED, REPO_ID)
        assert shared._remote_service is None
        assert "expired" in shared.get_remote_degraded_reason().lower()

    def test_skips_remote_when_unreachable(self, monkeypatch):
        shared.clear_remote_service()
        monkeypatch.setattr(RemoteTextService, "ping", lambda self, timeout=2.0: False)
        shared.configure_remote_service("http://127.0.0.1:8080", _FUTURE, REPO_ID)
        assert shared._remote_service is None
        assert "unreachable" in shared.get_remote_degraded_reason().lower()

    def test_uses_remote_when_healthy(self, monkeypatch):
        shared.clear_remote_service()
        monkeypatch.setattr(RemoteTextService, "ping", lambda self, timeout=2.0: True)
        shared.configure_remote_service("http://127.0.0.1:8080", _FUTURE, REPO_ID)
        assert shared._remote_service is not None
        assert shared.get_remote_degraded_reason() == ""
