"""Shared image detection and loading helpers.

Used by both the vision_analyze tool and the TUI drag-and-drop input flow.
"""

from __future__ import annotations

import base64
import logging
import os
import shlex
from pathlib import Path

from attocode.tools.vision import _detect_mime, _validate_file_path
from attocode.types.messages import ImageSource, ImageSourceType

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}

# Max image file size: 20 MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024


def extract_image_paths(text: str) -> tuple[str, list[str]]:
    """Extract image file paths from user text input.

    Uses shell-style tokenization (shlex) to correctly handle:
    - Backslash-escaped spaces from macOS drag-drop:
        /Users/me/Screenshot\\ 2026-03-05\\ at\\ 18.42.57.png
    - Quoted paths: "/Users/me/My Photos/img.png"
    - Simple unquoted paths: /tmp/image.png
    - Multiple images in one prompt

    Returns (remaining_text, list_of_image_paths).
    """
    # Use shell-style tokenization — handles \\ escapes and quotes
    try:
        tokens = shlex.split(text)
    except ValueError:
        # Unbalanced quotes or other parse error — fall back to simple split
        tokens = text.split()

    image_paths: list[str] = []
    remaining_tokens: list[str] = []

    for token in tokens:
        if _is_image_extension(token):
            resolved = _resolve_path(token)
            if resolved and os.path.isfile(resolved):
                image_paths.append(resolved)
                continue
        remaining_tokens.append(token)

    remaining = " ".join(remaining_tokens).strip()
    return remaining, image_paths


def load_image_to_source(
    path: str,
    working_dir: str | None = None,
) -> ImageSource | None:
    """Load an image file and return an ImageSource (base64-encoded).

    Returns None if the file cannot be loaded (with a logged warning).
    """
    # Validate path security
    if working_dir:
        error = _validate_file_path(path, working_dir)
        if error:
            logger.warning("image_path_rejected: %s (%s)", path, error)
            return None

    try:
        file_path = Path(path)
        if not file_path.is_file():
            logger.warning("image_not_found: %s", path)
            return None

        size = file_path.stat().st_size
        if size > MAX_IMAGE_SIZE:
            logger.warning("image_too_large: %s (%d bytes)", path, size)
            return None

        image_bytes = file_path.read_bytes()
        media_type = _detect_mime(str(file_path))
        b64_data = base64.b64encode(image_bytes).decode("ascii")

        return ImageSource(
            type=ImageSourceType.BASE64,
            media_type=media_type,
            data=b64_data,
        )
    except Exception as e:
        logger.warning("image_load_failed: %s (%s)", path, e)
        return None


def _is_image_extension(path_str: str) -> bool:
    """Check if a path has a recognized image extension."""
    ext = Path(path_str).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def _resolve_path(path_str: str) -> str | None:
    """Resolve a path string, expanding ~ and making absolute."""
    try:
        expanded = os.path.expanduser(path_str)
        return str(Path(expanded).resolve())
    except (ValueError, OSError):
        return None
