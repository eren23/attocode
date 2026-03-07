"""Tests for RequestLoggingMiddleware."""

from __future__ import annotations

import logging

import httpx
import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig


@pytest.fixture()
async def logging_client():
    deps.reset()
    config = CodeIntelConfig()
    app = create_app(config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    deps.reset()


@pytest.mark.asyncio
async def test_logging_middleware_logs_request(logging_client, caplog):
    with caplog.at_level(logging.INFO, logger="attocode.code_intel.api.middleware"):
        await logging_client.get("/health")
    assert "GET" in caplog.text
    assert "/health" in caplog.text
    assert "200" in caplog.text


@pytest.mark.asyncio
async def test_logging_middleware_logs_duration(logging_client, caplog):
    with caplog.at_level(logging.INFO, logger="attocode.code_intel.api.middleware"):
        await logging_client.get("/health")
    assert "ms" in caplog.text
