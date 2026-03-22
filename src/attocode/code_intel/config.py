"""Configuration for the code intelligence service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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

    # Indexing settings
    file_cap: int = 5000  # Max files to index; higher = better coverage, slower bootstrap

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
    embedding_nl_mode: str = "none"  # "none" = embed raw code, "heuristic" = code-to-NL before embedding

    # Remote connection (CLI → server bridge)
    remote_url: str = ""  # e.g. "https://code.example.com"
    remote_token: str = ""  # JWT or API key for remote server
    remote_repo_id: str = ""  # UUID of the repo on the remote server

    # GC settings
    gc_merged_branch_retention_days: int = 7
    gc_inactive_branch_retention_days: int = 30
    gc_content_min_age_minutes: int = 60

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
            file_cap=int(os.environ.get("ATTOCODE_FILE_CAP", "5000")),
            database_url=os.environ.get("DATABASE_URL", ""),
            secret_key=os.environ.get("SECRET_KEY", ""),
            redis_url=os.environ.get("REDIS_URL", ""),
            git_clone_dir=os.environ.get("GIT_CLONE_DIR", "/var/lib/code-intel/repos"),
            git_clone_max_gb=float(os.environ.get("GIT_CLONE_MAX_GB", "50")),
            git_ssh_key_path=os.environ.get("GIT_SSH_KEY_PATH", ""),
            embedding_model=os.environ.get("ATTOCODE_EMBEDDING_MODEL", ""),
            embedding_dimension=int(os.environ.get("ATTOCODE_EMBEDDING_DIMENSION", "0")),
            embedding_nl_mode=os.environ.get("ATTOCODE_NL_EMBEDDING_MODE", "none"),
            gc_merged_branch_retention_days=int(os.environ.get("GC_MERGED_BRANCH_RETENTION_DAYS", "7")),
            gc_inactive_branch_retention_days=int(os.environ.get("GC_INACTIVE_BRANCH_RETENTION_DAYS", "30")),
            gc_content_min_age_minutes=int(os.environ.get("GC_CONTENT_MIN_AGE_MINUTES", "60")),
            jwt_expiry_minutes=int(os.environ.get("JWT_EXPIRY_MINUTES", "60")),
            refresh_expiry_days=int(os.environ.get("REFRESH_EXPIRY_DAYS", "30")),
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            base_url=os.environ.get("ATTOCODE_BASE_URL", ""),
            registration_key=os.environ.get("REGISTRATION_KEY", ""),
            remote_url=os.environ.get("ATTOCODE_REMOTE_URL", ""),
            remote_token=os.environ.get("ATTOCODE_REMOTE_TOKEN", ""),
            remote_repo_id=os.environ.get("ATTOCODE_REMOTE_REPO_ID", ""),
        )


@dataclass(slots=True)
class RemoteConfig:
    """Remote server connection configuration, persisted to .attocode/config.toml."""

    server: str = ""
    token: str = ""
    repo_id: str = ""
    branch_auto_detect: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.server and self.token)


def load_remote_config(project_dir: str) -> RemoteConfig:
    """Load remote config from .attocode/config.toml, falling back to env vars."""
    config_path = Path(project_dir) / ".attocode" / "config.toml"

    rc = RemoteConfig()

    if config_path.exists():
        try:
            import tomllib
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
            remote = data.get("remote", {})
            rc.server = remote.get("server", "")
            rc.token = remote.get("token", "")
            rc.repo_id = remote.get("repo_id", "")
            rc.branch_auto_detect = remote.get("branch_auto_detect", True)
        except Exception:
            pass

    # Env vars override file config
    if os.environ.get("ATTOCODE_REMOTE_URL"):
        rc.server = os.environ["ATTOCODE_REMOTE_URL"]
    if os.environ.get("ATTOCODE_REMOTE_TOKEN"):
        rc.token = os.environ["ATTOCODE_REMOTE_TOKEN"]
    if os.environ.get("ATTOCODE_REMOTE_REPO_ID"):
        rc.repo_id = os.environ["ATTOCODE_REMOTE_REPO_ID"]

    return rc


def save_remote_config(project_dir: str, rc: RemoteConfig) -> Path:
    """Save remote config to .attocode/config.toml. Returns the config path."""
    config_path = Path(project_dir) / ".attocode" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve existing config sections
    existing: dict = {}
    if config_path.exists():
        try:
            import tomllib
            existing = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing["remote"] = {
        "server": rc.server,
        "token": rc.token,
        "repo_id": rc.repo_id,
        "branch_auto_detect": rc.branch_auto_detect,
    }

    # Write TOML manually (tomllib is read-only, avoid tomli_w dependency)
    lines: list[str] = []
    for section, values in existing.items():
        if isinstance(values, dict):
            lines.append(f"[{section}]")
            for k, v in values.items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path
