"""Dependency injection for the HTTP API."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService

logger = logging.getLogger(__name__)

# Module-level singletons set during app startup
_config: CodeIntelConfig | None = None
_services: dict[str, CodeIntelService] = {}
_default_project_id: str = ""


def configure(config: CodeIntelConfig) -> None:
    """Initialize the DI container with a config. Called once at app startup."""
    global _config, _default_project_id
    if _config is not None:
        logger.warning("configure() called more than once; overwriting previous config")
    _config = config
    if config.project_dir:
        svc = CodeIntelService.get_instance(config.project_dir, config)
        _default_project_id = "default"
        _services["default"] = svc


def reset() -> None:
    """Reset all state. For test isolation only."""
    global _config, _default_project_id
    _config = None
    _services.clear()
    _default_project_id = ""


def get_config() -> CodeIntelConfig:
    """Return the active config."""
    if _config is None:
        return CodeIntelConfig.from_env()
    return _config


def get_service(project_id: str = "") -> CodeIntelService:
    """Return the CodeIntelService for a project.

    For Phase 1, only a single project is supported (the default).
    Multi-project support comes in Phase 2.
    """
    pid = project_id or _default_project_id
    if pid not in _services:
        raise ValueError(f"Project '{pid}' not found. Register it first via POST /api/v1/projects")
    return _services[pid]


def get_service_or_404(project_id: str) -> CodeIntelService:
    """Return the service for a project or raise HTTP 404."""
    try:
        return get_service(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


def register_project(project_id: str, path: str, name: str = "") -> CodeIntelService:
    """Register a new project and return its service instance."""
    svc = CodeIntelService.get_instance(path, _config)
    _services[project_id] = svc
    return svc


def list_projects() -> dict[str, CodeIntelService]:
    """Return all registered projects."""
    return dict(_services)


def get_default_project_id() -> str:
    """Return the default project ID."""
    return _default_project_id
