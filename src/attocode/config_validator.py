"""Configuration validation utilities."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from attocode.errors import ConfigurationError

if TYPE_CHECKING:
    from attocode.config import AttoConfig

KNOWN_PROVIDERS = {"anthropic", "openrouter", "openai", "zai", "minimax"}

# Providers whose API keys must start with "sk-"
SK_PREFIX_PROVIDERS = {"anthropic", "openrouter", "openai"}


def validate_config(config: AttoConfig) -> None:
    """Validate an AttoConfig, raising ConfigurationError on problems.

    Checks performed:
    - api_key format (length >= 10, "sk-" prefix for applicable providers)
    - working_directory exists and is a directory
    - provider is one of the known providers
    - model is a non-empty string
    - session_dir parent exists (when session_dir is set)
    """
    # -- Provider -----------------------------------------------------------
    if config.provider not in KNOWN_PROVIDERS:
        raise ConfigurationError(
            f"Unknown provider {config.provider!r}. "
            f"Must be one of: {', '.join(sorted(KNOWN_PROVIDERS))}"
        )

    # -- Model --------------------------------------------------------------
    if not config.model or not config.model.strip():
        raise ConfigurationError("Model must be a non-empty string.")

    # -- API key format -----------------------------------------------------
    if config.api_key is not None:
        if len(config.api_key) < 10:
            raise ConfigurationError(
                "API key is too short (must be at least 10 characters)."
            )
        if config.provider in SK_PREFIX_PROVIDERS and not config.api_key.startswith("sk-"):
            raise ConfigurationError(
                f"API key for provider {config.provider!r} must start with 'sk-'."
            )

    # -- Working directory --------------------------------------------------
    if config.working_directory:
        wd = Path(config.working_directory)
        if not wd.exists():
            raise ConfigurationError(
                f"Working directory does not exist: {config.working_directory}"
            )
        if not wd.is_dir():
            raise ConfigurationError(
                f"Working directory is not a directory: {config.working_directory}"
            )

    # -- Session directory --------------------------------------------------
    if config.session_dir:
        parent = Path(config.session_dir).parent
        if not parent.exists():
            raise ConfigurationError(
                f"Parent of session_dir does not exist: {parent}"
            )


def validate_provider_importable(provider: str) -> None:
    """Verify that the required SDK for *provider* is installed.

    Raises ConfigurationError when the import fails.
    For ``openrouter`` and ``zai`` no extra package is needed (they use httpx).
    """
    if provider == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "The 'anthropic' package is required for the anthropic provider. "
                "Install it with: pip install anthropic"
            ) from exc
    elif provider == "openai":
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "The 'openai' package is required for the openai provider. "
                "Install it with: pip install openai"
            ) from exc
    # openrouter and zai use httpx — no extra import check needed.
