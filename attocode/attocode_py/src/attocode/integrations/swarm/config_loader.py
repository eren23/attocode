"""Swarm YAML config loader — parses swarm.yaml and merges with defaults."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import yaml

from attocode.integrations.swarm.types import (
    AutoSplitConfig,
    CompletionGuardConfig,
    DEFAULT_SWARM_CONFIG,
    HierarchyConfig,
    HierarchyRoleConfig,
    SwarmConfig,
    SwarmWorkerSpec,
    TaskTypeConfig,
    WorkerCapability,
)


# =============================================================================
# YAML Parsing
# =============================================================================


def parse_swarm_yaml(content: str) -> dict[str, Any]:
    """Parse YAML content into a dictionary.

    Uses PyYAML's safe_load for robust YAML parsing including:
    - Key-value pairs (``key: value``)
    - Nested objects via indentation
    - Block arrays with ``- item`` syntax
    - Type coercion: true/false -> bool, numeric -> number, null/~ -> None
    - Inline comments stripped
    - Quoted strings preserved

    Returns an empty dict on empty/None content.
    """
    result = yaml.safe_load(content)
    return result if isinstance(result, dict) else {}


# =============================================================================
# File Discovery
# =============================================================================


_SEARCH_PATHS = [
    ".attocode/swarm.yaml",
    ".attocode/swarm.yml",
    ".attocode/swarm.json",
]


def load_swarm_yaml_config(cwd: str | None = None) -> dict[str, Any] | None:
    """Load swarm config from the first matching config file.

    Search order (first match wins):
      1. ``{cwd}/.attocode/swarm.yaml``
      2. ``{cwd}/.attocode/swarm.yml``
      3. ``{cwd}/.attocode/swarm.json``
      4. ``~/.attocode/swarm.yaml``

    Returns ``None`` if no config file is found.
    """
    base_dir = cwd or os.getcwd()

    # Project-level search
    for rel_path in _SEARCH_PATHS:
        full_path = os.path.join(base_dir, rel_path)
        if os.path.isfile(full_path):
            return _load_config_file(full_path)

    # User-level fallback
    user_yaml = os.path.join(Path.home(), ".attocode", "swarm.yaml")
    if os.path.isfile(user_yaml):
        return _load_config_file(user_yaml)

    return None


def _load_config_file(path: str) -> dict[str, Any] | None:
    """Load a single config file (YAML or JSON)."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    if path.endswith(".json"):
        try:
            result = json.loads(content)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return None

    return parse_swarm_yaml(content)


# =============================================================================
# YAML to SwarmConfig Mapping
# =============================================================================


def _get_nested(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict, trying multiple key variants."""
    for key in keys:
        parts = key.split(".")
        current: Any = raw
        for part in parts:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current is not None:
            return current
    return default


def _to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    result: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            result.append("_")
        result.append(ch.lower())
    return "".join(result)


def _parse_worker_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a raw worker dict into SwarmWorkerSpec-compatible fields."""
    spec: dict[str, Any] = {}

    spec["name"] = raw.get("name", "worker")
    spec["model"] = raw.get("model", "")

    # Count shortcut: expand to multiple identical specs upstream
    # (handled by caller, not stored in spec)

    if "capabilities" in raw:
        spec["capabilities"] = normalize_capabilities(raw["capabilities"])
    elif "capability" in raw:
        # Single capability string
        spec["capabilities"] = normalize_capabilities([raw["capability"]])

    for field_name in (
        "context_window", "contextWindow",
        "persona", "role",
        "max_tokens", "maxTokens",
        "policy_profile", "policyProfile",
        "prompt_tier", "promptTier",
    ):
        snake = _to_snake(field_name)
        if field_name in raw:
            spec[snake] = raw[field_name]

    for list_field in ("allowed_tools", "allowedTools", "denied_tools",
                       "deniedTools", "extra_tools", "extraTools"):
        snake = _to_snake(list_field)
        if list_field in raw:
            val = raw[list_field]
            spec[snake] = list(val) if isinstance(val, (list, tuple)) else [val]

    return spec


def yaml_to_swarm_config(
    raw: dict[str, Any],
    orchestrator_model: str,
) -> dict[str, Any]:
    """Map raw YAML sections to SwarmConfig-compatible fields.

    Supports both camelCase and snake_case keys in the YAML input.
    Returns a flat dict of SwarmConfig field overrides.
    """
    cfg: dict[str, Any] = {}

    # --- Models ---
    models = raw.get("models", raw.get("model", {}))
    if isinstance(models, dict):
        cfg["orchestrator_model"] = models.get(
            "orchestrator", models.get("orchestrator_model", orchestrator_model)
        )
        planner = models.get("planner", models.get("planner_model"))
        if planner:
            cfg["planner_model"] = planner
        qg_model = models.get("quality_gate", models.get("qualityGate",
                              models.get("quality_gate_model")))
        if qg_model:
            cfg["quality_gate_model"] = qg_model
    elif isinstance(models, str):
        # Single model string applies to orchestrator
        cfg["orchestrator_model"] = models
    else:
        cfg["orchestrator_model"] = orchestrator_model

    # Fallback orchestrator model from top-level keys
    if "orchestrator_model" not in cfg or not cfg["orchestrator_model"]:
        top_orch = raw.get("orchestrator", raw.get("orchestrator_model"))
        if isinstance(top_orch, dict):
            cfg["orchestrator_model"] = top_orch.get("model", orchestrator_model)
        elif isinstance(top_orch, str):
            cfg["orchestrator_model"] = top_orch
        else:
            cfg["orchestrator_model"] = orchestrator_model

    # --- Workers ---
    raw_workers = raw.get("workers", [])
    if isinstance(raw_workers, list):
        workers: list[dict[str, Any]] = []
        for w in raw_workers:
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            spec = _parse_worker_spec(w)
            for i in range(max(1, int(count))):
                entry = dict(spec)
                if count > 1:
                    entry["name"] = f"{spec.get('name', 'worker')}-{i}"
                workers.append(entry)
        if workers:
            cfg["workers"] = workers

    # --- Budget ---
    budget = raw.get("budget", {})
    if isinstance(budget, dict):
        total = budget.get("total_tokens", budget.get("totalTokens"))
        if total is not None:
            cfg["total_budget"] = int(total)
        max_cost = budget.get("max_cost", budget.get("maxCost"))
        if max_cost is not None:
            cfg["max_cost"] = float(max_cost)
        max_conc = budget.get("max_concurrency", budget.get("maxConcurrency"))
        if max_conc is not None:
            cfg["max_concurrency"] = int(max_conc)

    # Top-level overrides for concurrency
    for key in ("max_concurrency", "maxConcurrency"):
        if key in raw and "max_concurrency" not in cfg:
            cfg["max_concurrency"] = int(raw[key])

    # --- Quality ---
    quality = raw.get("quality", {})
    if isinstance(quality, dict):
        enabled = quality.get("enabled", quality.get("gates"))
        if enabled is not None:
            cfg["quality_gates"] = bool(enabled)
        threshold = quality.get("threshold", quality.get("quality_threshold"))
        if threshold is not None:
            cfg["quality_threshold"] = int(threshold)
    elif isinstance(quality, bool):
        cfg["quality_gates"] = quality

    # Top-level qualityGates
    for key in ("quality_gates", "qualityGates"):
        if key in raw and "quality_gates" not in cfg:
            cfg["quality_gates"] = bool(raw[key])

    # --- Resilience ---
    resilience = raw.get("resilience", {})
    if isinstance(resilience, dict):
        retries = resilience.get("worker_retries", resilience.get("workerRetries"))
        if retries is not None:
            cfg["worker_retries"] = int(retries)
        failover = resilience.get("model_failover", resilience.get("modelFailover"))
        if failover is not None:
            cfg["enable_model_failover"] = bool(failover)

    # --- Features ---
    features = raw.get("features", {})
    if isinstance(features, dict):
        _feature_map = {
            "planning": "enable_planning",
            "wave_review": "enable_wave_review",
            "waveReview": "enable_wave_review",
            "verification": "enable_verification",
            "persistence": "enable_persistence",
        }
        for yaml_key, config_key in _feature_map.items():
            val = features.get(yaml_key)
            if val is not None:
                cfg[config_key] = bool(val)

    # --- Hierarchy ---
    hierarchy = raw.get("hierarchy", {})
    if isinstance(hierarchy, dict):
        h_cfg: dict[str, Any] = {}
        for role in ("manager", "judge"):
            role_data = hierarchy.get(role)
            if isinstance(role_data, dict):
                h_cfg[role] = role_data
            elif isinstance(role_data, str):
                h_cfg[role] = {"model": role_data}
        if h_cfg:
            cfg["hierarchy"] = h_cfg

    # --- Throttle ---
    throttle = raw.get("throttle")
    if throttle is not None:
        cfg["throttle"] = throttle

    # --- Paid only ---
    paid_only = raw.get("paid_only", raw.get("paidOnly"))
    if paid_only is not None:
        cfg["paid_only"] = bool(paid_only)

    # --- Auto-split ---
    auto_split = raw.get("auto_split", raw.get("autoSplit", {}))
    if isinstance(auto_split, dict) and auto_split:
        cfg["auto_split"] = auto_split

    # --- Completion guard ---
    guard = raw.get("completion_guard", raw.get("completionGuard", {}))
    if isinstance(guard, dict) and guard:
        cfg["completion_guard"] = guard

    # --- Misc top-level fields (snake_case and camelCase) ---
    _direct_mappings: dict[str, tuple[str, type]] = {
        "worker_timeout": ("worker_timeout", int),
        "workerTimeout": ("worker_timeout", int),
        "worker_max_iterations": ("worker_max_iterations", int),
        "workerMaxIterations": ("worker_max_iterations", int),
        "dispatch_stagger_ms": ("dispatch_stagger_ms", int),
        "dispatchStaggerMs": ("dispatch_stagger_ms", int),
        "state_dir": ("state_dir", str),
        "stateDir": ("state_dir", str),
        "philosophy": ("philosophy", str),
        "probe_models": ("probe_models", bool),
        "probeModels": ("probe_models", bool),
        "hollow_termination_ratio": ("hollow_termination_ratio", float),
        "hollowTerminationRatio": ("hollow_termination_ratio", float),
        "enable_hollow_termination": ("enable_hollow_termination", bool),
        "enableHollowTermination": ("enable_hollow_termination", bool),
    }
    for yaml_key, (config_key, coerce) in _direct_mappings.items():
        if yaml_key in raw and config_key not in cfg:
            cfg[config_key] = coerce(raw[yaml_key])

    return cfg


# =============================================================================
# Three-Way Merge
# =============================================================================


def merge_swarm_configs(
    defaults: SwarmConfig,
    yaml_config: dict[str, Any] | None,
    cli_overrides: dict[str, Any],
) -> SwarmConfig:
    """Three-way merge: defaults < yaml < CLI.

    Special rules:
    - ``orchestrator_model`` from CLI only wins if
      ``orchestrator_model_explicit=True`` in *cli_overrides*.
    - When ``paid_only=True`` and yaml doesn't set throttle,
      default throttle to ``'paid'``.
    """
    # Start from defaults as a dict
    result = asdict(defaults)

    # Layer 1: YAML overrides
    if yaml_config:
        for key, value in yaml_config.items():
            if key in result:
                result[key] = value

    # Layer 2: CLI overrides
    orch_explicit = cli_overrides.pop("orchestrator_model_explicit", False)
    for key, value in cli_overrides.items():
        if value is None:
            continue
        if key == "orchestrator_model" and not orch_explicit:
            continue
        if key in result:
            result[key] = value

    # Special: paid_only -> throttle default
    if result.get("paid_only") and not (yaml_config and "throttle" in yaml_config):
        result["throttle"] = "paid"

    # Reconstruct dataclass instances for nested fields
    return _dict_to_swarm_config(result)


def _dict_to_swarm_config(data: dict[str, Any]) -> SwarmConfig:
    """Reconstruct a SwarmConfig from a flat/nested dict."""
    # Workers: convert list[dict] -> list[SwarmWorkerSpec]
    if "workers" in data and data["workers"]:
        workers: list[SwarmWorkerSpec] = []
        for w in data["workers"]:
            if isinstance(w, SwarmWorkerSpec):
                workers.append(w)
            elif isinstance(w, dict):
                # Filter to valid SwarmWorkerSpec fields
                valid_fields = {f.name for f in fields(SwarmWorkerSpec)}
                filtered = {k: v for k, v in w.items() if k in valid_fields}
                # Ensure capabilities are WorkerCapability enums
                if "capabilities" in filtered:
                    filtered["capabilities"] = [
                        WorkerCapability(c) if isinstance(c, str) else c
                        for c in filtered["capabilities"]
                    ]
                if "role" in filtered and isinstance(filtered["role"], str):
                    from attocode.integrations.swarm.types import WorkerRole
                    filtered["role"] = WorkerRole(filtered["role"])
                workers.append(SwarmWorkerSpec(**filtered))
        data["workers"] = workers

    # Hierarchy
    if "hierarchy" in data and isinstance(data["hierarchy"], dict):
        h = data["hierarchy"]
        if not isinstance(h, HierarchyConfig):
            manager = h.get("manager", {})
            judge = h.get("judge", {})
            data["hierarchy"] = HierarchyConfig(
                manager=HierarchyRoleConfig(**(manager if isinstance(manager, dict) else {})),
                judge=HierarchyRoleConfig(**(judge if isinstance(judge, dict) else {})),
            )

    # AutoSplitConfig
    if "auto_split" in data and isinstance(data["auto_split"], dict):
        data["auto_split"] = AutoSplitConfig(**{
            k: v for k, v in data["auto_split"].items()
            if k in {f.name for f in fields(AutoSplitConfig)}
        })

    # CompletionGuardConfig
    if "completion_guard" in data and isinstance(data["completion_guard"], dict):
        data["completion_guard"] = CompletionGuardConfig(**{
            k: v for k, v in data["completion_guard"].items()
            if k in {f.name for f in fields(CompletionGuardConfig)}
        })

    # Filter to valid SwarmConfig fields
    valid_fields = {f.name for f in fields(SwarmConfig)}
    filtered_data = {k: v for k, v in data.items() if k in valid_fields}

    return SwarmConfig(**filtered_data)


# =============================================================================
# Model Validation
# =============================================================================


def normalize_swarm_model_config(
    config: SwarmConfig,
) -> tuple[SwarmConfig, list[str]]:
    """Validate model IDs and auto-correct malformed ones.

    Model IDs should be in ``provider/name`` format (e.g.,
    ``anthropic/claude-sonnet-4-20250514``). Returns the corrected
    config and a list of warning messages.
    """
    warnings: list[str] = []

    def _validate_model(model_id: str, label: str) -> str:
        if not model_id:
            return model_id
        if "/" in model_id:
            return model_id
        # Auto-correct: bare model names get prefixed
        corrected = _guess_provider_prefix(model_id)
        if corrected != model_id:
            warnings.append(
                f"{label}: '{model_id}' -> '{corrected}' (auto-corrected)"
            )
        return corrected

    config.orchestrator_model = _validate_model(
        config.orchestrator_model, "orchestrator_model"
    )
    config.planner_model = _validate_model(
        config.planner_model, "planner_model"
    )
    config.quality_gate_model = _validate_model(
        config.quality_gate_model, "quality_gate_model"
    )

    for worker in config.workers:
        worker.model = _validate_model(worker.model, f"worker[{worker.name}]")

    if config.hierarchy.manager.model:
        config.hierarchy.manager.model = _validate_model(
            config.hierarchy.manager.model, "hierarchy.manager"
        )
    if config.hierarchy.judge.model:
        config.hierarchy.judge.model = _validate_model(
            config.hierarchy.judge.model, "hierarchy.judge"
        )

    return config, warnings


def _guess_provider_prefix(model_id: str) -> str:
    """Attempt to guess the provider prefix for a bare model ID."""
    lower = model_id.lower()
    provider_hints: dict[str, str] = {
        "claude": "anthropic",
        "gpt": "openai",
        "o1": "openai",
        "o3": "openai",
        "o4": "openai",
        "mistral": "mistralai",
        "ministral": "mistralai",
        "gemini": "google",
        "llama": "meta-llama",
        "qwen": "qwen",
        "deepseek": "deepseek",
        "command": "cohere",
    }
    for hint, provider in provider_hints.items():
        if lower.startswith(hint):
            return f"{provider}/{model_id}"
    # Cannot guess — return as-is
    return model_id


# =============================================================================
# Capability Normalization
# =============================================================================

_CAPABILITY_ALIASES: dict[str, WorkerCapability] = {
    "refactor": WorkerCapability.CODE,
    "implement": WorkerCapability.CODE,
    "coding": WorkerCapability.CODE,
    "writing": WorkerCapability.WRITE,
    "synthesis": WorkerCapability.WRITE,
    "merge": WorkerCapability.WRITE,
    "docs": WorkerCapability.DOCUMENT,
    "testing": WorkerCapability.TEST,
    "reviewing": WorkerCapability.REVIEW,
    "researching": WorkerCapability.RESEARCH,
}


def normalize_capabilities(raw: list[str]) -> list[WorkerCapability]:
    """Normalize a list of capability strings into WorkerCapability enums.

    Applies alias mappings (e.g. ``refactor`` -> ``code``), drops unknown
    values, deduplicates, and falls back to ``[WorkerCapability.CODE]``
    if the result is empty.
    """
    capabilities: list[WorkerCapability] = []
    seen: set[WorkerCapability] = set()

    for item in raw:
        lower = item.strip().lower()

        # Direct enum match
        cap: WorkerCapability | None = None
        try:
            cap = WorkerCapability(lower)
        except ValueError:
            pass

        # Alias match
        if cap is None:
            cap = _CAPABILITY_ALIASES.get(lower)

        if cap is not None and cap not in seen:
            capabilities.append(cap)
            seen.add(cap)

    return capabilities if capabilities else [WorkerCapability.CODE]
