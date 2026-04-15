"""Harness configuration for meta-harness optimization.

Defines the tunable parameter surface, valid ranges, and YAML
serialization for code-intel search scoring configs.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from typing import Any

import yaml

from attocode.integrations.context.semantic_search import SearchScoringConfig


# Valid ranges for each parameter — used for proposal validation
PARAMETER_RANGES: dict[str, tuple[float, float]] = {
    "bm25_k1": (0.5, 3.0),
    "bm25_b": (0.0, 1.0),
    "name_exact_boost": (1.0, 10.0),
    "name_substring_boost": (1.0, 5.0),
    "name_token_boost": (1.0, 3.0),
    "class_boost": (1.0, 3.0),
    "function_boost": (1.0, 2.0),
    "method_boost": (1.0, 2.0),
    "src_dir_boost": (1.0, 2.0),
    "multi_term_high_bonus": (1.0, 3.0),
    "multi_term_med_bonus": (1.0, 2.0),
    "multi_term_high_threshold": (0.5, 1.0),
    "multi_term_med_threshold": (0.2, 0.8),
    "non_code_penalty": (0.05, 1.0),
    "config_penalty": (0.01, 1.0),
    "test_penalty": (0.1, 1.0),
    "exact_phrase_bonus": (1.0, 3.0),
    "max_chunks_per_file": (1, 10),
    "wide_k_multiplier": (2, 15),
    "wide_k_min": (10, 200),
    "rrf_k": (10, 200),
}


@dataclass
class HarnessConfig:
    """Full tunable configuration surface for code-intel search.

    Wraps SearchScoringConfig with YAML I/O, validation, and
    application to a CodeIntelService instance.
    """

    scoring: SearchScoringConfig

    def __init__(self, scoring: SearchScoringConfig | None = None, **overrides: Any) -> None:
        if scoring is not None:
            self.scoring = scoring
        else:
            # Build from defaults + overrides
            valid_fields = {f.name for f in fields(SearchScoringConfig)}
            kwargs = {k: v for k, v in overrides.items() if k in valid_fields}
            self.scoring = SearchScoringConfig(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict."""
        return asdict(self.scoring)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarnessConfig:
        """Create from plain dict with type coercion for int fields."""
        valid_fields = {f.name: f for f in fields(SearchScoringConfig)}
        kwargs: dict[str, Any] = {}
        for k, v in data.items():
            if k not in valid_fields:
                continue
            # Coerce float->int for integer-typed fields (YAML/LLM may emit floats)
            field_type = valid_fields[k].type
            if field_type == "int" and isinstance(v, float):
                v = int(round(v))
            kwargs[k] = v
        return cls(scoring=SearchScoringConfig(**kwargs))

    def save_yaml(self, path: str) -> None:
        """Write config to YAML file."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=True)

    @classmethod
    def load_yaml(cls, path: str) -> HarnessConfig:
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def validate(self) -> list[str]:
        """Check all parameters are within valid ranges.

        Returns list of error messages (empty = valid).
        """
        errors: list[str] = []
        d = self.to_dict()
        for param, (lo, hi) in PARAMETER_RANGES.items():
            val = d.get(param)
            if val is None:
                continue
            if not (lo <= val <= hi):
                errors.append(f"{param}={val} out of range [{lo}, {hi}]")

        # Cross-parameter constraints
        med = d.get("multi_term_med_threshold", 0.5)
        high = d.get("multi_term_high_threshold", 0.8)
        if med >= high:
            errors.append(
                f"multi_term_med_threshold ({med}) must be < "
                f"multi_term_high_threshold ({high})"
            )
        return errors

    def apply_to_service(self, svc) -> None:
        """Apply this config to a CodeIntelService instance."""
        svc.set_scoring_config(self.scoring)

    @classmethod
    def default(cls) -> HarnessConfig:
        """Return config with all default values."""
        return cls(scoring=SearchScoringConfig())
