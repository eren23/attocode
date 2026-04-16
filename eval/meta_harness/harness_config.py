"""Harness configuration for meta-harness optimization.

Defines the tunable parameter surface, valid ranges, and YAML
serialization for code-intel search scoring configs.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from typing import Any

import yaml

from attocode.integrations.context.semantic_search import ContextAssemblyConfig, SearchScoringConfig


# Valid ranges for search scoring parameters
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
    "importance_weight": (0.0, 2.0),
    "frecency_weight": (0.0, 1.0),
    "rerank_confidence_threshold": (0.0, 0.9),
    "dep_proximity_weight": (0.0, 1.0),
    "dep_proximity_seed_count": (1, 15),
    "kw_dominance_threshold": (1.0, 5.0),
    "rrf_k_keyword_high_conf": (5, 60),
    "rrf_k_vector_low_conf": (50, 500),
}

# Valid ranges for context assembly parameters
CONTEXT_PARAMETER_RANGES: dict[str, tuple[float, float]] = {
    "small_repo_threshold": (20, 500),
    "large_repo_threshold": (1000, 20000),
    "summary_ratio": (0.1, 0.6),
    "structure_ratio": (0.1, 0.6),
    "conventions_ratio": (0.02, 0.3),
    "search_ratio": (0.02, 0.3),
    "summary_ratio_no_hint": (0.1, 0.6),
    "structure_ratio_no_hint": (0.1, 0.7),
    "conventions_ratio_no_hint": (0.02, 0.3),
    "medium_structure_map_ratio": (0.3, 0.9),
    "explore_max_items": (5, 50),
    "explore_importance_threshold": (0.05, 0.8),
    "bootstrap_hotspots_n": (3, 30),
    "conventions_sample_size": (5, 100),
    "bootstrap_search_top_k": (3, 20),
    "max_depth": (1, 4),
    "center_symbol_cap": (3, 20),
    "neighbor_symbol_cap": (2, 15),
    "param_preview_limit": (2, 8),
    "base_preview_limit": (1, 6),
    "method_preview_limit": (2, 10),
}


def _coerce_int_fields(data: dict[str, Any], config_cls) -> dict[str, Any]:
    """Coerce float->int for integer-typed fields in a dataclass."""
    valid_fields = {f.name: f for f in fields(config_cls)}
    result: dict[str, Any] = {}
    for k, v in data.items():
        if k not in valid_fields:
            continue
        if valid_fields[k].type == "int" and isinstance(v, float):
            v = int(round(v))
        result[k] = v
    return result


@dataclass
class HarnessConfig:
    """Full tunable configuration surface for code-intel.

    Wraps both SearchScoringConfig and ContextAssemblyConfig with
    YAML I/O, validation, and application to a CodeIntelService.
    """

    scoring: SearchScoringConfig
    context: ContextAssemblyConfig

    def __init__(
        self,
        scoring: SearchScoringConfig | None = None,
        context: ContextAssemblyConfig | None = None,
        **overrides: Any,
    ) -> None:
        if scoring is not None:
            self.scoring = scoring
        else:
            scoring_fields = {f.name for f in fields(SearchScoringConfig)}
            kwargs = {k: v for k, v in overrides.items() if k in scoring_fields}
            self.scoring = SearchScoringConfig(**kwargs)

        if context is not None:
            self.context = context
        else:
            context_fields = {f.name for f in fields(ContextAssemblyConfig)}
            kwargs = {k: v for k, v in overrides.items() if k in context_fields}
            self.context = ContextAssemblyConfig(**kwargs) if kwargs else ContextAssemblyConfig()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict with namespaced keys."""
        d = asdict(self.scoring)
        d["context"] = asdict(self.context)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarnessConfig:
        """Create from plain dict with type coercion."""
        # Context params may be nested or flat
        context_data = data.pop("context", None) if isinstance(data.get("context"), dict) else None

        scoring_kwargs = _coerce_int_fields(data, SearchScoringConfig)
        scoring = SearchScoringConfig(**scoring_kwargs)

        if context_data:
            context_kwargs = _coerce_int_fields(context_data, ContextAssemblyConfig)
            context = ContextAssemblyConfig(**context_kwargs)
        else:
            # Try flat keys that belong to ContextAssemblyConfig
            context_fields = {f.name for f in fields(ContextAssemblyConfig)}
            ctx_flat = {k: v for k, v in data.items() if k in context_fields}
            if ctx_flat:
                context_kwargs = _coerce_int_fields(ctx_flat, ContextAssemblyConfig)
                context = ContextAssemblyConfig(**context_kwargs)
            else:
                context = ContextAssemblyConfig()

        return cls(scoring=scoring, context=context)

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
        """Check all parameters are within valid ranges."""
        errors: list[str] = []

        # Search scoring validation
        scoring_dict = asdict(self.scoring)
        for param, (lo, hi) in PARAMETER_RANGES.items():
            val = scoring_dict.get(param)
            if val is not None and not (lo <= val <= hi):
                errors.append(f"{param}={val} out of range [{lo}, {hi}]")

        med = scoring_dict.get("multi_term_med_threshold", 0.5)
        high = scoring_dict.get("multi_term_high_threshold", 0.8)
        if med >= high:
            errors.append(f"multi_term_med_threshold ({med}) must be < multi_term_high_threshold ({high})")

        # Context assembly validation
        context_dict = asdict(self.context)
        for param, (lo, hi) in CONTEXT_PARAMETER_RANGES.items():
            val = context_dict.get(param)
            if val is not None and not (lo <= val <= hi):
                errors.append(f"context.{param}={val} out of range [{lo}, {hi}]")

        # Budget ratios should sum to ~1.0
        hint_sum = self.context.summary_ratio + self.context.structure_ratio + self.context.conventions_ratio + self.context.search_ratio
        if not (0.8 <= hint_sum <= 1.2):
            errors.append(f"context budget ratios (with hint) sum to {hint_sum:.2f}, expected ~1.0")

        no_hint_sum = self.context.summary_ratio_no_hint + self.context.structure_ratio_no_hint + self.context.conventions_ratio_no_hint
        if not (0.8 <= no_hint_sum <= 1.2):
            errors.append(f"context budget ratios (no hint) sum to {no_hint_sum:.2f}, expected ~1.0")

        return errors

    def apply_to_service(self, svc) -> None:
        """Apply this config to a CodeIntelService instance."""
        svc.set_scoring_config(self.scoring)
        svc.set_context_config(self.context)

    @classmethod
    def default(cls) -> HarnessConfig:
        """Return config with all default values."""
        return cls(scoring=SearchScoringConfig(), context=ContextAssemblyConfig())
