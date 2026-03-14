"""Configuration for the code intelligence service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(slots=True)
class CodeIntelConfig:
    """Configuration for the CodeIntelService."""

    # Core settings (Phase 1)
    project_dir: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    log_level: str = "info"

    # Service mode (multi-user)
    database_url: str = ""
    secret_key: str = ""
    redis_url: str = ""

    # Git clone settings
    git_clone_dir: str = "/var/lib/code-intel/repos"
    git_clone_max_gb: float = 50.0
    git_ssh_key_path: str = ""

    # Embedding settings
    embedding_model: str = ""  # auto-detect or explicit: all-MiniLM-L6-v2 | nomic-embed-text | openai
    embedding_dimension: int = 0  # 0 = auto from model

    # Auth settings
    jwt_expiry_minutes: int = 60
    refresh_expiry_days: int = 30
    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = ""  # e.g. "https://code.example.com" — for OAuth redirect_uri
    registration_key: str = ""  # When set, required in register request to prevent open signup

    @property
    def is_service_mode(self) -> bool:
        """True when DATABASE_URL is set — enables multi-user service features."""
        return bool(self.database_url)

    @property
    def effective_base_url(self) -> str:
        """Base URL for OAuth redirect URIs. Falls back to http://host:port."""
        if self.base_url:
            return self.base_url.rstrip("/")
        return f"http://{self.host}:{self.port}"

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
            database_url=os.environ.get("DATABASE_URL", ""),
            secret_key=os.environ.get("SECRET_KEY", ""),
            redis_url=os.environ.get("REDIS_URL", ""),
            git_clone_dir=os.environ.get("GIT_CLONE_DIR", "/var/lib/code-intel/repos"),
            git_clone_max_gb=float(os.environ.get("GIT_CLONE_MAX_GB", "50")),
            git_ssh_key_path=os.environ.get("GIT_SSH_KEY_PATH", ""),
            embedding_model=os.environ.get("ATTOCODE_EMBEDDING_MODEL", ""),
            embedding_dimension=int(os.environ.get("ATTOCODE_EMBEDDING_DIMENSION", "0")),
            jwt_expiry_minutes=int(os.environ.get("JWT_EXPIRY_MINUTES", "60")),
            refresh_expiry_days=int(os.environ.get("REFRESH_EXPIRY_DAYS", "30")),
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            base_url=os.environ.get("ATTOCODE_BASE_URL", ""),
            registration_key=os.environ.get("REGISTRATION_KEY", ""),
        )
