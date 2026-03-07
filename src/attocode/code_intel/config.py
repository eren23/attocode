"""Configuration for the code intelligence service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(slots=True)
class CodeIntelConfig:
    """Configuration for the CodeIntelService."""

    project_dir: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> CodeIntelConfig:
        """Build config from environment variables."""
        return cls(
            project_dir=os.environ.get("ATTOCODE_PROJECT_DIR", ""),
            host=os.environ.get("ATTOCODE_HOST", "127.0.0.1"),
            port=int(os.environ.get("ATTOCODE_PORT", "8080")),
            api_key=os.environ.get("ATTOCODE_API_KEY", ""),
            cors_origins=os.environ.get("ATTOCODE_CORS_ORIGINS", "*").split(","),
            log_level=os.environ.get("ATTOCODE_LOG_LEVEL", "info"),
        )
