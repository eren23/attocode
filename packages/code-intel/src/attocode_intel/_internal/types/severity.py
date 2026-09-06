"""Shared severity levels for findings, security patterns, etc."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Finding severity level."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
