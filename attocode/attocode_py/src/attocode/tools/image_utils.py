"""Shared image detection and loading helpers.

Used by both the vision_analyze tool and the TUI drag-and-drop input flow.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path

from attocode.tools.vision import _detect_mime, _validate_file_path
from attocode.types.messages import ImageSource, ImageSourceType

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}

# Max image file size: 20 MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024

# Regex for quoted paths: "..." or '...'
_QUOTED_PATH_RE = re.compile(r"""(['"])((?:(?!\1).)+\.[a-zA-Z]{2,5})\1""")

# Regex for unquoted paths: /absolute or ./relative or ~/home, ending with image ext
_UNQUOTED_PATH_RE = re.compile(
    r"""(?:^|\s)((?:[/~.]|[A-Za-z]:[\\/])"""  # starts with / ~ . or drive letter
    r"""[^\s'"]*\.[a-zA-Z]{2,5})"""  # rest of path with extension
    r"""(?=\s|$)""",
)


def extract_image_paths(text: str) -> tuple[str, list[str]]:
    """Extract image file paths from user text input.

    Handles:
    - Bare file paths: /path/to/image.png
    - Quoted paths: "/path/to/image.png" or '/path/to/image.png'
    - Paths with ~ (home directory)
    - Multiple images in one prompt

    Returns (remaining_text, list_of_image_paths).
    """
    image_paths: list[str] = []
    remaining = text

    # First pass: quoted paths
    for match in _QUOTED_PATH_RE.finditer(text):
        path_str = match.group(2)
        if _is_image_extension(path_str):
            resolved = _resolve_path(path_str)
            if resolved and os.path.isfile(resolved):
                image_paths.append(resolved)
                # Remove the entire quoted match (including quotes) from remaining
                remaining = remaining.replace(match.group(0), "", 1)

    # Second pass: unquoted paths (on the remaining text after quoted removal)
    for match in _UNQUOTED_PATH_RE.finditer(remaining):
        path_str = match.group(1)
        if _is_image_extension(path_str):
            resolved = _resolve_path(path_str)
            if resolved and os.path.isfile(resolved):
                image_paths.append(resolved)
                remaining = remaining.replace(path_str, "", 1)

    # Clean up extra whitespace
    remaining = " ".join(remaining.split()).strip()

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
