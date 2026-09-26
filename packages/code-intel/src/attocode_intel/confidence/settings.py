"""Workspace-scoped scorer settings; never copy repository keys into os.environ."""

from __future__ import annotations

import logging
import os
import tomllib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from attocode_intel._internal.integrations.feature_flags import registry

logger = logging.getLogger(__name__)
_project: ContextVar[str] = ContextVar("confidence_project", default="")
_disabled: ContextVar[bool] = ContextVar("confidence_disabled", default=False)


def project_dir() -> str:
    from attocode_intel.request_context import current_request

    request = current_request.get()
    if request is not None and request.source != "local":
        return ""  # Hosted repositories cannot configure provider credentials.
    return _project.get() or (request.project_dir if request else "")


@contextmanager
def workspace(path: str):
    token = _project.set(path)
    try:
        yield
    finally:
        _project.reset(token)


@contextmanager
def disabled():
    """Rule assertion tests must remain deterministic even in a live workspace."""
    token = _disabled.set(True)
    try:
        yield
    finally:
        _disabled.reset(token)


def local_settings() -> dict:
    root = project_dir()
    if not root:
        return {}
    try:
        value = tomllib.loads((Path(root) / ".attocode/config.toml").read_text())["confidence"]
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, KeyError):
        return {}


def selected() -> str:
    if _disabled.get():
        return "off"
    return registry.resolve_with_default("CONFIDENCE", local_settings().get("scorer", "off"))


def mode() -> str:
    return registry.resolve_with_default("CONFIDENCE_MODE", local_settings().get("mode", "shadow"))


def environment() -> dict[str, str]:
    """Credentials/settings for this request, with process environment precedence."""
    from dotenv import dotenv_values

    root = project_dir()
    values = dotenv_values(Path(root) / ".env") if root else {}
    return {**{k: v for k, v in values.items() if v is not None}, **os.environ}
