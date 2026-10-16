"""Utility functions for the sample project."""

import os
import json


def parse_config(path: str) -> dict:
    """Parse a configuration file and return settings."""
    if not os.path.exists(path):
        return {"default": True}
    with open(path) as f:
        return json.load(f)


def validate_input(value: str) -> bool:
    """Validate that input is non-empty and reasonable length."""
    if not value or not value.strip():
        raise ValueError("Input cannot be empty")
    if len(value) > 255:
        raise ValueError("Input too long")
    return True


def format_output(data: dict) -> str:
    """Format data dictionary as a readable string."""
    return "\n".join(f"{k}: {v}" for k, v in sorted(data.items()))
