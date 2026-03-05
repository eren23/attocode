"""Tests for the vision_analyze tool."""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.tools.vision import (
    _detect_mime,
    _is_base64,
    _is_url,
    _validate_file_path,
    _validate_url,
    create_vision_tool,
)
from attocode.types.messages import ChatResponse, StopReason


# ---------------------------------------------------------------------------
# Input detection helpers
# ---------------------------------------------------------------------------


class TestInputDetection:
    def test_is_url_http(self) -> None:
        assert _is_url("http://example.com/img.png") is True

    def test_is_url_https(self) -> None:
        assert _is_url("https://example.com/img.png") is True

    def test_is_url_file_path(self) -> None:
        assert _is_url("/tmp/image.png") is False

    def test_is_url_base64(self) -> None:
        assert _is_url("iVBORw0KGgoAAAANSU") is False

    def test_is_base64_valid(self) -> None:
        data = base64.b64encode(b"x" * 32).decode()
        assert _is_base64(data) is True

    def test_is_base64_invalid(self) -> None:
        assert _is_base64("not-base64!!!") is False

    def test_is_base64_too_short(self) -> None:
        data = base64.b64encode(b"x").decode()
        assert _is_base64(data) is False

    def test_detect_mime_png(self) -> None:
        assert _detect_mime("photo.png") == "image/png"

    def test_detect_mime_jpg(self) -> None:
        assert _detect_mime("photo.jpg") == "image/jpeg"

    def test_detect_mime_unknown(self) -> None:
        assert _detect_mime("file.xyz123") == "image/png"  # fallback


# ---------------------------------------------------------------------------
# URL / path validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validate_url_rejects_http(self) -> None:
        err = _validate_url("http://example.com/img.png")
        assert err is not None
        assert "https" in err

    def test_validate_url_accepts_https(self) -> None:
        # Patch _is_private_ip to avoid DNS resolution in tests
        with patch("attocode.tools.vision._is_private_ip", return_value=False):
            assert _validate_url("https://example.com/img.png") is None

    def test_validate_url_rejects_private_ip(self) -> None:
        with patch("attocode.tools.vision._is_private_ip", return_value=True):
            err = _validate_url("https://internal.local/img.png")
            assert err is not None
            assert "private" in err

    def test_validate_url_rejects_no_hostname(self) -> None:
        err = _validate_url("https:///no-host")
        assert err is not None

    def test_validate_file_path_within_working_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _validate_file_path(os.path.join(tmpdir, "img.png"), tmpdir) is None

    def test_validate_file_path_outside_working_dir(self) -> None:
        err = _validate_file_path("/etc/passwd", "/home/user/project")
        assert err is not None
        assert "working directory" in err

    def test_validate_file_path_no_working_dir(self) -> None:
        # When no working_dir is set, validation passes
        assert _validate_file_path("/any/path.png", None) is None


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------


class TestVisionToolSpec:
    def test_tool_creation(self) -> None:
        tool = create_vision_tool(provider_name="mock", api_key="test")
        assert tool.name == "vision_analyze"
        assert tool.danger_level.value == "moderate"
        assert "vision" in tool.tags

    def test_tool_definition(self) -> None:
        tool = create_vision_tool(provider_name="mock", api_key="test")
        defn = tool.to_definition()
        assert defn.name == "vision_analyze"
        assert "image" in defn.parameters["required"]
        assert "prompt" in defn.parameters["properties"]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


class TestVisionToolExecution:
    @pytest.mark.asyncio
    async def test_local_file_analysis(self) -> None:
        """Test analyzing a local image file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = os.path.join(tmpdir, "test.png")
            with open(tmp_path, "wb") as f:
                f.write(b"\x89PNG\r\n" + b"\x00" * 100)

            tool = create_vision_tool(provider_name="mock", api_key="test", working_dir=tmpdir)
            mock_response = ChatResponse(content="A test image", stop_reason=StopReason.END_TURN)
            mock_provider = MagicMock()
            mock_provider.chat = AsyncMock(return_value=mock_response)

            with patch("attocode.providers.registry.create_provider", return_value=mock_provider):
                result = await tool.execute({"image": tmp_path, "prompt": "What is this?"})
                assert result == "A test image"

    @pytest.mark.asyncio
    async def test_local_file_outside_working_dir_rejected(self) -> None:
        """Test that files outside working_dir are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = create_vision_tool(provider_name="mock", api_key="test", working_dir=tmpdir)
            # /etc/hosts exists on macOS/Linux and is outside tmpdir
            result = await tool.execute({"image": "/etc/hosts"})
            assert "working directory" in result

    @pytest.mark.asyncio
    async def test_base64_analysis(self) -> None:
        """Test analyzing a base64-encoded image."""
        tool = create_vision_tool(provider_name="mock", api_key="test")

        mock_response = ChatResponse(content="Base64 image analysis", stop_reason=StopReason.END_TURN)
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        b64_data = base64.b64encode(b"\x89PNG" + b"\x00" * 100).decode()

        with patch("attocode.providers.registry.create_provider", return_value=mock_provider):
            result = await tool.execute({"image": b64_data})
            assert result == "Base64 image analysis"

    @pytest.mark.asyncio
    async def test_url_rejects_http(self) -> None:
        """Test that http URLs are rejected."""
        tool = create_vision_tool(provider_name="mock", api_key="test")
        result = await tool.execute({"image": "http://example.com/img.png"})
        assert "https" in result

    @pytest.mark.asyncio
    async def test_url_rejects_private_ip(self) -> None:
        """Test that URLs resolving to private IPs are rejected."""
        tool = create_vision_tool(provider_name="mock", api_key="test")
        with patch("attocode.tools.vision._is_private_ip", return_value=True):
            result = await tool.execute({"image": "https://internal.corp/secret"})
            assert "private" in result

    @pytest.mark.asyncio
    async def test_url_download_failure(self) -> None:
        """Test graceful handling of URL download failure."""
        tool = create_vision_tool(provider_name="mock", api_key="test")

        with patch("attocode.tools.vision._is_private_ip", return_value=False):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await tool.execute({"image": "https://example.com/broken.jpg"})
                assert "Error downloading image" in result

    @pytest.mark.asyncio
    async def test_invalid_image_input(self) -> None:
        """Test error message for invalid image input."""
        tool = create_vision_tool(provider_name="mock", api_key="test")

        result = await tool.execute({"image": "not-a-url-not-a-path-not-base64"})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_default_prompt(self) -> None:
        """Test that default prompt is used when none provided."""
        tool = create_vision_tool(provider_name="mock", api_key="test")

        mock_response = ChatResponse(content="Description", stop_reason=StopReason.END_TURN)
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        b64_data = base64.b64encode(b"\x89PNG" + b"\x00" * 100).decode()

        with patch("attocode.providers.registry.create_provider", return_value=mock_provider):
            result = await tool.execute({"image": b64_data})
            assert result == "Description"
            # Verify the default prompt was sent
            call_args = mock_provider.chat.call_args
            messages = call_args[0][0]
            assert len(messages) == 1
            # Content should be a list with text + image blocks (text first)
            content = messages[0].content
            assert isinstance(content, list)
            assert len(content) == 2
            assert content[0].text == "Describe this image in detail."


# ---------------------------------------------------------------------------
# Image path extraction (image_utils)
# ---------------------------------------------------------------------------


class TestExtractImagePaths:
    """Tests for extract_image_paths from image_utils."""

    def test_no_images(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        remaining, images = extract_image_paths("Hello, explain this code")
        assert remaining == "Hello, explain this code"
        assert images == []

    def test_bare_path(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "screenshot.png")
            Path(img).write_bytes(b"\x89PNG\r\n" + b"\x00" * 10)
            text = f"Explain this {img}"
            remaining, images = extract_image_paths(text)
            assert len(images) == 1
            assert images[0] == str(Path(img).resolve())
            assert "screenshot.png" not in remaining

    def test_quoted_path(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "my image.png")
            Path(img).write_bytes(b"\x89PNG\r\n" + b"\x00" * 10)
            text = f'Explain this "{img}"'
            remaining, images = extract_image_paths(text)
            assert len(images) == 1
            assert "my image.png" not in remaining

    def test_multiple_images(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = os.path.join(tmpdir, "a.png")
            img2 = os.path.join(tmpdir, "b.jpg")
            Path(img1).write_bytes(b"\x89PNG" + b"\x00" * 10)
            Path(img2).write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
            text = f"Compare {img1} and {img2}"
            remaining, images = extract_image_paths(text)
            assert len(images) == 2
            assert "Compare" in remaining

    def test_nonexistent_file_ignored(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        text = "Explain /tmp/nonexistent_xyzzy_image.png"
        remaining, images = extract_image_paths(text)
        assert images == []

    def test_non_image_extension_ignored(self) -> None:
        from attocode.tools.image_utils import extract_image_paths
        with tempfile.TemporaryDirectory() as tmpdir:
            txt = os.path.join(tmpdir, "notes.txt")
            Path(txt).write_bytes(b"hello")
            text = f"Read {txt}"
            remaining, images = extract_image_paths(text)
            assert images == []


# ---------------------------------------------------------------------------
# load_image_to_source
# ---------------------------------------------------------------------------


class TestLoadImageToSource:
    def test_load_valid_image(self) -> None:
        from attocode.tools.image_utils import load_image_to_source
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "test.png")
            Path(img).write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)
            source = load_image_to_source(img)
            assert source is not None
            assert source.type == "base64"
            assert source.media_type == "image/png"
            assert len(source.data) > 0

    def test_reject_outside_working_dir(self) -> None:
        from attocode.tools.image_utils import load_image_to_source
        with tempfile.TemporaryDirectory() as tmpdir:
            source = load_image_to_source("/etc/hosts", working_dir=tmpdir)
            assert source is None

    def test_nonexistent_file(self) -> None:
        from attocode.tools.image_utils import load_image_to_source
        source = load_image_to_source("/tmp/does_not_exist_xyzzy.png")
        assert source is None

    def test_too_large_file(self) -> None:
        from attocode.tools.image_utils import MAX_IMAGE_SIZE, load_image_to_source
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "big.png")
            Path(img).write_bytes(b"\x00" * (MAX_IMAGE_SIZE + 1))
            source = load_image_to_source(img)
            assert source is None


# ---------------------------------------------------------------------------
# build_initial_messages with images
# ---------------------------------------------------------------------------


class TestBuildInitialMessagesWithImages:
    def test_without_images(self) -> None:
        from attocode.agent.message_builder import build_initial_messages
        msgs = build_initial_messages("Hello")
        assert len(msgs) == 2
        assert msgs[1].role.value == "user"
        assert msgs[1].content == "Hello"

    def test_with_images(self) -> None:
        from attocode.agent.message_builder import build_initial_messages
        from attocode.types.messages import MessageWithStructuredContent
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "test.png")
            Path(img).write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)
            msgs = build_initial_messages("Explain this", images=[img])
            assert len(msgs) == 2
            user_msg = msgs[1]
            assert isinstance(user_msg, MessageWithStructuredContent)
            assert isinstance(user_msg.content, list)
            assert len(user_msg.content) == 2  # text + image
            assert user_msg.content[0].text == "Explain this"
            assert user_msg.content[1].type == "image"

    def test_with_no_text_uses_default_prompt(self) -> None:
        from attocode.agent.message_builder import build_initial_messages
        from attocode.types.messages import MessageWithStructuredContent
        with tempfile.TemporaryDirectory() as tmpdir:
            img = os.path.join(tmpdir, "test.jpg")
            Path(img).write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
            msgs = build_initial_messages("", images=[img])
            user_msg = msgs[1]
            assert isinstance(user_msg, MessageWithStructuredContent)
            assert user_msg.content[0].text == "Describe this image."

    def test_with_invalid_image_falls_back(self) -> None:
        from attocode.agent.message_builder import build_initial_messages
        from attocode.types.messages import Message
        msgs = build_initial_messages("Hello", images=["/nonexistent.png"])
        # Invalid image should be skipped, falling back to plain message
        user_msg = msgs[1]
        assert isinstance(user_msg, Message)
        assert user_msg.content == "Hello"
