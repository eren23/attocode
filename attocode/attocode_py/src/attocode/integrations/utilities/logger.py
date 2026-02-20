"""Structured logging using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def setup_logging(*, debug: bool = False, json_output: bool = False) -> None:
    """Configure structlog for the application.

    Args:
        debug: Enable DEBUG level logging.
        json_output: Use JSON output format instead of console.
    """
    level = logging.DEBUG if debug else logging.INFO

    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "attocode", **kwargs: Any) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name, **kwargs)
