"""Vision analysis tool — analyze images via a vision-capable LLM."""

from __future__ import annotations

import base64
import ipaddress
import logging
import mimetypes
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel

logger = logging.getLogger(__name__)

# Cheap vision-capable fallback model for OpenRouter
_FALLBACK_VISION_MODEL = "google/gemini-2.0-flash"

_MIME_FALLBACK = "image/png"


def _detect_mime(path: str) -> str:
    """Detect MIME type from file extension."""
    mime, _ = mimetypes.guess_type(path)
    return mime or _MIME_FALLBACK


def _is_url(image: str) -> bool:
    return image.startswith("http://") or image.startswith("https://")


def _is_base64(data: str) -> bool:
    """Quick check if a string is plausible base64 image data."""
    try:
        decoded = base64.b64decode(data, validate=True)
        return len(decoded) > 16
    except Exception:
        return False


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/link-local IP address."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for _family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError, OSError):
        # If we can't resolve, treat as suspicious
        return True
    return False


def _validate_url(url: str) -> str | None:
    """Validate a URL for safety. Returns error message or None if safe."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Error: only https URLs are allowed for image fetching"
    hostname = parsed.hostname
    if not hostname:
        return "Error: invalid URL — no hostname"
    if _is_private_ip(hostname):
        return "Error: cannot fetch images from private/internal network addresses"
    return None


def _validate_file_path(image: str, working_dir: str | None) -> str | None:
    """Validate a file path for safety. Returns error message or None if safe."""
    resolved = Path(image).resolve()
    if working_dir:
        work_resolved = Path(working_dir).resolve()
        if not str(resolved).startswith(str(work_resolved)):
            return "Error: image path must be within the working directory"
    return None


def create_vision_tool(
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    working_dir: str | None = None,
) -> Tool:
    """Create the vision_analyze tool.

    Uses the configured provider to analyze images. For providers that
    don't support vision on the current model, falls back to a cheap
    vision-capable model via OpenRouter.
    """
    async def _get_vision_provider() -> Any:
        """Create a vision-capable provider for this call."""
        from attocode.providers.registry import create_provider

        effective_provider = provider_name or "openrouter"
        effective_model = model

        # Check if the current model supports vision
        if effective_provider == "openrouter" and effective_model:
            from attocode.providers.model_cache import is_vision_capable
            if not is_vision_capable(effective_model):
                effective_model = _FALLBACK_VISION_MODEL
                logger.debug("Model %s lacks vision, falling back to %s", model, effective_model)

        try:
            return create_provider(
                effective_provider,
                api_key=api_key,
                model=effective_model,
            )
        except Exception:
            # Last resort: try OpenRouter with fallback model
            if effective_provider != "openrouter":
                return create_provider(
                    "openrouter",
                    model=_FALLBACK_VISION_MODEL,
                )
            raise

    async def execute(args: dict[str, Any]) -> str:
        image = args["image"]
        prompt = args.get("prompt", "Describe this image in detail.")

        from attocode.types.messages import (
            ChatOptions,
            ImageContentBlock,
            ImageSource,
            ImageSourceType,
            MessageWithStructuredContent,
            Role,
            TextContentBlock,
        )

        # Resolve image input to base64 + MIME type
        if _is_url(image):
            # Validate URL for SSRF protection
            url_error = _validate_url(image)
            if url_error:
                return url_error
            # Download the image
            try:
                import httpx
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                    resp = await client.get(image)
                    resp.raise_for_status()
                    image_bytes = resp.content
                    ct = resp.headers.get("content-type", _MIME_FALLBACK)
                    content_type = ct.split(";")[0].strip()
                    b64_data = base64.b64encode(image_bytes).decode("ascii")
            except Exception as e:
                return f"Error downloading image: {e}"
            source = ImageSource(
                type=ImageSourceType.BASE64, media_type=content_type, data=b64_data,
            )

        elif os.path.exists(image):
            # Validate file path against working directory
            path_error = _validate_file_path(image, working_dir)
            if path_error:
                return path_error
            # Read local file
            try:
                path = Path(image)
                image_bytes = path.read_bytes()
                media_type = _detect_mime(str(path))
                b64_data = base64.b64encode(image_bytes).decode("ascii")
            except Exception as e:
                return f"Error reading image file: {e}"
            source = ImageSource(type=ImageSourceType.BASE64, media_type=media_type, data=b64_data)

        elif _is_base64(image):
            # Raw base64 data
            source = ImageSource(type=ImageSourceType.BASE64, media_type=_MIME_FALLBACK, data=image)

        else:
            return "Error: image must be a URL, file path, or base64-encoded data"

        # Build message with prompt + image (text before image per convention)
        msg = MessageWithStructuredContent(
            role=Role.USER,
            content=[
                TextContentBlock(text=prompt),
                ImageContentBlock(source=source),
            ],
        )

        try:
            provider = await _get_vision_provider()
            response = await provider.chat(
                [msg],
                ChatOptions(max_tokens=2048),
            )
            return response.content or "No analysis returned."
        except Exception as e:
            return f"Error analyzing image: {e}"

    spec = ToolSpec(
        name="vision_analyze",
        description=(
            "Analyze an image using a vision-capable LLM. "
            "Accepts a URL, local file path, or base64-encoded image data. "
            "Optionally provide a prompt to guide the analysis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": (
                        "Image URL (http/https), file path, or base64 data."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Optional prompt to guide the analysis."
                    ),
                },
            },
            "required": ["image"],
        },
        danger_level=DangerLevel.MODERATE,
    )

    return Tool(spec=spec, execute=execute, tags=["vision"])
