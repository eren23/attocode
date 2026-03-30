"""Integration test for MCP remote mode proxied through a live ASGI app."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import httpx
import pytest
from starlette.testclient import TestClient

from attocode.code_intel import server as srv
from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService


class _SyncASGIClientAdapter:
    """Minimal sync adapter exposing the subset used by RemoteTextService."""

    def __init__(self, app, headers: dict[str, str] | None = None) -> None:
        self._client = TestClient(app)
        self._headers = headers or {}

    def get(self, path: str, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self._client.get(path, headers=headers, **kwargs)

    def post(self, path: str, **kwargs):
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return self._client.post(path, headers=headers, **kwargs)

    def close(self) -> None:
        self._client.close()


def _make_mock_service(project_dir: str = "/tmp/remote-project") -> MagicMock:
    svc = MagicMock(spec=CodeIntelService)
    type(svc).project_dir = PropertyMock(return_value=project_dir)
    for method in (
        "repo_map",
        "dead_code",
        "change_coupling",
        "fast_search",
    ):
        getattr(svc, method).return_value = f"stub:{method}"
    return svc


def _reset_remote_state() -> None:
    deps.reset()
    CodeIntelService._reset_instances()
    srv.clear_remote_service()
    if "_service" in srv.__dict__:
        del srv.__dict__["_service"]
    if "_remote_service" in srv.__dict__:
        del srv.__dict__["_remote_service"]
    srv._ast_service = None
    srv._context_mgr = None
    srv._code_analyzer = None
    srv._explorer = None


@pytest.mark.integration
def test_remote_mcp_tools_proxy_through_live_http_app(monkeypatch) -> None:
    from attocode.code_intel.tools.history_tools import change_coupling

    _reset_remote_state()

    config = CodeIntelConfig(project_dir="/tmp/remote-project")
    app = create_app(config)
    mock_service = _make_mock_service()
    deps._services["default"] = mock_service

    def _client_factory(*args, **kwargs):
        return _SyncASGIClientAdapter(app, headers=kwargs.get("headers"))

    monkeypatch.setattr(httpx, "Client", _client_factory)

    srv.configure_remote_service("http://test", "tok_test", "default")
    try:
        assert srv.repo_map() == "stub:repo_map"
        assert srv.dead_code() == "stub:dead_code"
        assert change_coupling("src/main.py") == "stub:change_coupling"
        assert srv.fast_search("main") == "stub:fast_search"

        mock_service.repo_map.assert_called_once()
        mock_service.dead_code.assert_called_once()
        mock_service.change_coupling.assert_called_once()
        mock_service.fast_search.assert_called_once()
    finally:
        _reset_remote_state()
