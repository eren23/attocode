"""Configuration loading and management."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env files
load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPERATURE = 0.0

# Config directory names
PROJECT_DIR = ".attocode"
USER_DIR_NAME = ".attocode"

# Provider defaults for setup wizard
PROVIDER_MODEL_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openrouter": "anthropic/claude-sonnet-4",
    "openai": "gpt-5.4-mini",
    "zai": "glm-5",
    "minimax": "MiniMax-M2.7",
}

PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "zai": "ZAI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}

PROVIDER_MODEL_OPTIONS: dict[str, list[str]] = {
    "anthropic": [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-haiku-3-20250714",
    ],
    "openrouter": [
        "anthropic/claude-sonnet-4",
        "anthropic/claude-opus-4",
        "openai/gpt-4o",
    ],
    "openai": [
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-4o",
        "o3-mini",
    ],
    "zai": [
        "glm-5",
    ],
    "minimax": [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ],
}


@dataclass(slots=True)
class AttoConfig:
    """Merged configuration from all sources.

    Priority: CLI args > env vars > project config > user config > defaults
    """
    # Provider
    provider: str = "anthropic"
    model: str = DEFAULT_MODEL
    api_key: str | None = None

    # Execution
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE

    # Dual model (architect/editor split)
    architect_model: str = ""
    editor_model: str = ""

    max_iterations: int = 100
    max_context_tokens: int = 200_000
    compaction_warning_threshold: float = 0.7
    compaction_threshold: float = 0.8
    timeout: float = 600.0

    # Budget
    budget_max_tokens: int = 100_000_000
    budget_max_cost: float = 10.0
    budget_max_duration: float = 7200.0

    # Paths
    working_directory: str = ""
    session_dir: str = ""
    project_root: str = ""

    # Features
    sandbox_mode: str = "auto"
    debug: bool = False

    # Session resume
    resume_session: str | None = None
    resume_session_explicit: bool = False

    # Permission mode
    permission_mode: str = "interactive"

    # Swarm
    swarm: bool = False
    swarm_config: str | None = None
    swarm_resume: str | None = None
    swarm_hybrid: bool = False
    paid_only: bool = False

    # Recording
    record: bool = False

    # System prompt override
    system_prompt: str | None = None

    # OpenRouter preferences
    openrouter_preferences: dict[str, Any] | None = None

    # Rules
    rules: list[str] = field(default_factory=list)

    def freeze(self) -> FrozenAttoConfig:
        """Snapshot current config. Returns an immutable copy for use within a single turn."""
        import copy
        return FrozenAttoConfig(copy.copy(self))


class FrozenAttoConfig:
    """Immutable wrapper around AttoConfig for turn-level consistency.

    Delegates attribute reads to the wrapped config but prevents mutation.
    """
    __slots__ = ("_wrapped",)

    def __init__(self, config: AttoConfig) -> None:
        object.__setattr__(self, "_wrapped", config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"FrozenAttoConfig is immutable; cannot set '{name}'")

    def __repr__(self) -> str:
        return f"FrozenAttoConfig({self._wrapped!r})"


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the project root for a working directory."""
    return resolve_project_root(start).path


@dataclass(slots=True)
class ProjectRootResolution:
    """Resolved project root and the marker that identified it."""

    path: Path | None
    source: str = "none"


def resolve_project_root(start: Path | None = None) -> ProjectRootResolution:
    """Resolve the nearest project root.

    Walk upward from the current directory and stop at the first ancestor
    that looks like a project boundary. If both markers are present at the
    same directory, prefer ``.attocode``.
    """
    current = (start or Path.cwd()).resolve()

    for parent in [current, *current.parents]:
        if (parent / PROJECT_DIR).exists():
            return ProjectRootResolution(path=parent, source=".attocode")
        if (parent / ".git").exists():
            return ProjectRootResolution(path=parent, source=".git")

    return ProjectRootResolution(path=None, source="none")


def infer_project_root_from_session_dir(session_dir: str) -> str | None:
    """If *session_dir* is ``.../.attocode/sessions``, return the project root path."""
    if not str(session_dir).strip():
        return None
    try:
        session_path = Path(session_dir).resolve()
    except OSError:
        return None
    if session_path.name == "sessions" and session_path.parent.name == ".attocode":
        return str(session_path.parent.parent)
    return None


def get_user_config_dir() -> Path:
    """Get the user-level config directory (~/.attocode/)."""
    return Path.home() / USER_DIR_NAME


def load_json_config(path: Path) -> dict[str, Any]:
    """Load a JSON config file, returning empty dict if not found."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML config file, returning empty dict if not found."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, OSError):
        return {}


def load_rules(path: Path) -> str:
    """Load a rules.md file, returning empty string if not found."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_config(
    *,
    cli_args: dict[str, Any] | None = None,
    working_dir: str | None = None,
) -> AttoConfig:
    """Load configuration from all sources with proper priority.

    Priority: CLI args > env vars > project config > user config > defaults
    """
    config = AttoConfig()
    cli_args = cli_args or {}

    # Set working directory
    config.working_directory = working_dir or os.getcwd()

    # 1. User-level config (~/.attocode/config.json)
    user_dir = get_user_config_dir()
    user_config = load_json_config(user_dir / "config.json")
    _apply_dict(config, user_config)

    # Load user rules
    user_rules = load_rules(user_dir / "rules.md")
    if user_rules:
        config.rules.append(user_rules)

    # 2. Project-level config (.attocode/config.json)
    resolution = resolve_project_root(Path(config.working_directory))
    project_root = resolution.path
    if project_root:
        config.project_root = str(project_root)
        project_config = load_json_config(project_root / PROJECT_DIR / "config.json")
        _apply_dict(config, project_config)

        # Load project rules
        project_rules = load_rules(project_root / PROJECT_DIR / "rules.md")
        if project_rules:
            config.rules.append(project_rules)

        # Session directory
        if not config.session_dir:
            config.session_dir = str(project_root / PROJECT_DIR / "sessions")

    # 3. Environment variables — only as fallback when config files didn't set provider+key
    # Track whether provider/api_key were explicitly set by config files
    provider_from_config = config.provider != "anthropic" or config.api_key is not None
    model_explicitly_set = config.model != DEFAULT_MODEL
    if not provider_from_config:
        if api_key := os.environ.get("ANTHROPIC_API_KEY"):
            config.api_key = api_key
            config.provider = "anthropic"
        elif api_key := os.environ.get("OPENROUTER_API_KEY"):
            config.api_key = api_key
            config.provider = "openrouter"
        elif api_key := os.environ.get("OPENAI_API_KEY"):
            config.api_key = api_key
            config.provider = "openai"
        elif api_key := os.environ.get("ZAI_API_KEY"):
            config.api_key = api_key
            config.provider = "zai"

        # If provider was set from env and model wasn't explicitly configured,
        # use the provider-appropriate default model
        if not model_explicitly_set and config.provider in PROVIDER_MODEL_DEFAULTS:
            config.model = PROVIDER_MODEL_DEFAULTS[config.provider]

    if model := os.environ.get("ATTOCODE_MODEL"):
        config.model = model
    if debug := os.environ.get("ATTOCODE_DEBUG"):
        config.debug = debug.lower() in ("1", "true", "yes")

    # 4. CLI args (highest priority)
    _apply_dict(config, cli_args)

    # Default session dir
    if not config.session_dir:
        base = Path(config.project_root) if config.project_root else Path(config.working_directory)
        config.session_dir = str(base / PROJECT_DIR / "sessions")

    return config


def needs_setup(config: AttoConfig) -> bool:
    """True if no API key from any source (config files, env vars, CLI)."""
    if config.api_key:
        return False
    return not any(os.environ.get(v) for v in PROVIDER_ENV_VARS.values())


def save_global_config(data: dict[str, Any]) -> Path:
    """Read-modify-write ~/.attocode/config.json. Creates dir if needed."""
    config_dir = get_user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    existing = load_json_config(config_path)
    existing.update(data)
    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return config_path


def _apply_dict(config: AttoConfig, data: dict[str, Any]) -> None:
    """Apply dictionary values to config, only for known fields."""
    field_map = {
        "provider": "provider",
        "model": "model",
        "api_key": "api_key",
        "max_tokens": "max_tokens",
        "temperature": "temperature",
        "max_iterations": "max_iterations",
        "max_context_tokens": "max_context_tokens",
        "timeout": "timeout",
        "compaction_warning_threshold": "compaction_warning_threshold",
        "compaction_threshold": "compaction_threshold",
        "budget_max_tokens": "budget_max_tokens",
        "budget_max_cost": "budget_max_cost",
        "budget_max_duration": "budget_max_duration",
        "working_directory": "working_directory",
        "session_dir": "session_dir",
        "sandbox_mode": "sandbox_mode",
        "debug": "debug",
        "swarm": "swarm",
        "swarm_config": "swarm_config",
        "swarm_resume": "swarm_resume",
        "swarm_hybrid": "swarm_hybrid",
        "paid_only": "paid_only",
        "record": "record",
        "system_prompt": "system_prompt",
        "resume_session": "resume_session",
        "resume_session_explicit": "resume_session_explicit",
        "permission_mode": "permission_mode",
        # Aliases from JSON config
        "maxTokens": "max_tokens",
        "resumeSession": "resume_session",
        "resumeSessionExplicit": "resume_session_explicit",
        "permissionMode": "permission_mode",
        "maxIterations": "max_iterations",
        "maxContextTokens": "max_context_tokens",
        "compactionWarningThreshold": "compaction_warning_threshold",
        "compactionThreshold": "compaction_threshold",
        "sandboxMode": "sandbox_mode",
        "systemPrompt": "system_prompt",
        "openrouter_preferences": "openrouter_preferences",
        "openrouterPreferences": "openrouter_preferences",
        "architect_model": "architect_model",
        "editor_model": "editor_model",
        "architectModel": "architect_model",
        "editorModel": "editor_model",
    }
    compaction_block = data.get("compaction")
    if isinstance(compaction_block, dict):
        warning = compaction_block.get("warning_threshold", compaction_block.get("warningThreshold"))
        threshold = compaction_block.get("compaction_threshold", compaction_block.get("compactionThreshold"))
        if warning is not None:
            config.compaction_warning_threshold = float(warning)
        if threshold is not None:
            config.compaction_threshold = float(threshold)

    for key, attr in field_map.items():
        if key in data and data[key] is not None:
            setattr(config, attr, data[key])
