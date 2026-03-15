"""Tests for Redis Streams pubsub module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from attocode.code_intel.pubsub import get_stream_info, publish_event, subscribe


@pytest.fixture()
def mock_redis():
    return AsyncMock()


@pytest.fixture()
def _patch_redis(mock_redis: AsyncMock):
    with patch("attocode.code_intel.redis.get_redis", return_value=mock_redis):
        yield


# ---------------------------------------------------------------------------
# publish_event
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_redis")
class TestPublishEvent:
    async def test_calls_xadd_with_correct_stream_key(self, mock_redis: AsyncMock):
        mock_redis.xadd.return_value = "1234-0"
        await publish_event("repo-42", "indexing.started", {"branch": "main"})

        mock_redis.xadd.assert_awaited_once()
        args, kwargs = mock_redis.xadd.call_args
        assert args[0] == "repo:repo-42:stream"

    async def test_returns_entry_id_on_success(self, mock_redis: AsyncMock):
        mock_redis.xadd.return_value = "9999-1"
        result = await publish_event("r1", "test", {})
        assert result == "9999-1"

    async def test_returns_none_on_failure(self, mock_redis: AsyncMock):
        mock_redis.xadd.side_effect = ConnectionError("boom")
        result = await publish_event("r1", "test", {})
        assert result is None

    async def test_passes_maxlen_and_approximate(self, mock_redis: AsyncMock):
        mock_redis.xadd.return_value = "1-0"
        await publish_event("r1", "e", {"k": "v"})

        _, kwargs = mock_redis.xadd.call_args
        assert kwargs["maxlen"] == 10_000
        assert kwargs["approximate"] is True


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


def _make_xread_response(stream_key: str, entry_id: str, event_dict: dict):
    """Build a single-entry xread response list."""
    return [(stream_key, [(entry_id, {"event": json.dumps(event_dict)})])]


@pytest.mark.usefixtures("_patch_redis")
class TestSubscribe:
    async def test_passes_dollar_cursor_by_default(self, mock_redis: AsyncMock):
        """last_event_id defaults to '$' and is forwarded to xread."""
        mock_redis.xread = AsyncMock(
            side_effect=[
                _make_xread_response(
                    "repo:r1:stream", "100-0", {"type": "ping", "payload": {}}
                ),
            ],
        )

        gen = subscribe("r1")
        await gen.__anext__()
        await gen.aclose()

        first_call_args = mock_redis.xread.call_args_list[0]
        assert first_call_args[0][0] == {"repo:r1:stream": "$"}

    async def test_passes_explicit_cursor(self, mock_redis: AsyncMock):
        """last_event_id='0' is forwarded as-is to xread."""
        mock_redis.xread = AsyncMock(
            side_effect=[
                _make_xread_response(
                    "repo:r1:stream", "55-0", {"type": "replay", "payload": {}}
                ),
            ],
        )

        gen = subscribe("r1", last_event_id="0")
        await gen.__anext__()
        await gen.aclose()

        first_call_args = mock_redis.xread.call_args_list[0]
        assert first_call_args[0][0] == {"repo:r1:stream": "0"}

    async def test_yielded_dict_includes_stream_id(self, mock_redis: AsyncMock):
        mock_redis.xread = AsyncMock(
            side_effect=[
                _make_xread_response(
                    "repo:r1:stream",
                    "42-1",
                    {"type": "file.changed", "payload": {"path": "a.py"}},
                ),
            ],
        )

        gen = subscribe("r1")
        event = await gen.__anext__()
        await gen.aclose()

        assert event["_stream_id"] == "42-1"
        assert event["type"] == "file.changed"
        assert event["payload"] == {"path": "a.py"}

    async def test_handles_bytes_event_data(self, mock_redis: AsyncMock):
        """When Redis returns bytes fields, subscribe should decode them."""
        raw = json.dumps({"type": "bytes_test", "payload": {"x": 1}}).encode("utf-8")
        mock_redis.xread = AsyncMock(
            side_effect=[
                [("repo:r1:stream", [("200-0", {b"event": raw})])],
            ],
        )

        gen = subscribe("r1")
        event = await gen.__anext__()
        await gen.aclose()

        assert event["type"] == "bytes_test"
        assert event["payload"] == {"x": 1}
        assert event["_stream_id"] == "200-0"

    async def test_handles_bytes_entry_id(self, mock_redis: AsyncMock):
        """When entry_id is bytes, _stream_id should be decoded to str."""
        mock_redis.xread = AsyncMock(
            side_effect=[
                [(
                    "repo:r1:stream",
                    [(b"300-0", {"event": json.dumps({"type": "t", "payload": {}})})],
                )],
            ],
        )

        gen = subscribe("r1")
        event = await gen.__anext__()
        await gen.aclose()

        assert event["_stream_id"] == "300-0"
        assert isinstance(event["_stream_id"], str)

    async def test_skips_entries_with_invalid_json(self, mock_redis: AsyncMock):
        """Malformed JSON entries are silently skipped."""
        mock_redis.xread = AsyncMock(
            side_effect=[
                [(
                    "repo:r1:stream",
                    [
                        ("1-0", {"event": "not-json!!!"}),
                        ("2-0", {"event": json.dumps({"type": "ok", "payload": {}})}),
                    ],
                )],
            ],
        )

        gen = subscribe("r1")
        event = await gen.__anext__()
        await gen.aclose()

        assert event["type"] == "ok"
        assert event["_stream_id"] == "2-0"

    async def test_skips_entries_without_event_field(self, mock_redis: AsyncMock):
        """Entries that have no 'event' or b'event' field are skipped."""
        mock_redis.xread = AsyncMock(
            side_effect=[
                [(
                    "repo:r1:stream",
                    [
                        ("1-0", {"other_field": "value"}),
                        ("2-0", {"event": json.dumps({"type": "ok", "payload": {}})}),
                    ],
                )],
            ],
        )

        gen = subscribe("r1")
        event = await gen.__anext__()
        await gen.aclose()

        assert event["_stream_id"] == "2-0"


# ---------------------------------------------------------------------------
# get_stream_info
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_redis")
class TestGetStreamInfo:
    async def test_returns_length_first_last(self, mock_redis: AsyncMock):
        mock_redis.xinfo_stream.return_value = {
            "length": 150,
            "first-entry": ("1-0", {"event": "..."}),
            "last-entry": ("99-0", {"event": "..."}),
        }
        info = await get_stream_info("repo-7")

        assert info["length"] == 150
        assert info["first_entry"] == "1-0"
        assert info["last_entry"] == "99-0"

    async def test_calls_xinfo_with_correct_stream_key(self, mock_redis: AsyncMock):
        mock_redis.xinfo_stream.return_value = {"length": 0}
        await get_stream_info("my-repo")

        mock_redis.xinfo_stream.assert_awaited_once_with("repo:my-repo:stream")

    async def test_returns_defaults_on_error(self, mock_redis: AsyncMock):
        mock_redis.xinfo_stream.side_effect = ConnectionError("redis down")
        info = await get_stream_info("repo-x")

        assert info == {"length": 0, "first_entry": None, "last_entry": None}

    async def test_returns_defaults_when_stream_is_empty(self, mock_redis: AsyncMock):
        mock_redis.xinfo_stream.return_value = {
            "length": 0,
            "first-entry": None,
            "last-entry": None,
        }
        info = await get_stream_info("empty-repo")

        assert info["length"] == 0
        assert info["first_entry"] is None
        assert info["last_entry"] is None
