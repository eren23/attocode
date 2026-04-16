"""Centralized paths for meta-harness artifacts.

Separation of concerns:
- ``configs/`` (in source tree, TRACKED): canonical reference configs for reproducibility
- Ephemeral results (gitignored under ``.attocode/meta_harness/``): per-run outputs

Override via ``ATTOCODE_META_HARNESS_RESULTS`` env var.

Bench mode artifacts share the same results directory but use a per-bench
prefix on filenames (e.g. ``rule_baseline.json``, ``rule_evolution.jsonl``)
so multiple benches can coexist without clobbering each other.
"""

from __future__ import annotations

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tracked reference configs
CONFIGS_DIR = os.path.join(_PROJECT_ROOT, "eval", "meta_harness", "configs")
BASELINE_ORIGINAL_CONFIG = os.path.join(CONFIGS_DIR, "baseline_original.yaml")
BEST_CONFIG_REFERENCE = os.path.join(CONFIGS_DIR, "best_config.yaml")

# Ephemeral results — gitignored by living under .attocode/
DEFAULT_RESULTS_DIR = os.path.join(_PROJECT_ROOT, ".attocode", "meta_harness", "results")

# Default artifact filenames (search bench, no prefix for back-compat)
BASELINE_NAME = "baseline.json"
EVOLUTION_NAME = "evolution_summary.jsonl"
BEST_CONFIG_NAME = "best_config.yaml"


def results_dir() -> str:
    """Get the ephemeral results directory (env-overridable)."""
    return os.environ.get("ATTOCODE_META_HARNESS_RESULTS", DEFAULT_RESULTS_DIR)


def ensure_results_dir() -> str:
    """Ensure results directory exists and return its path."""
    path = results_dir()
    os.makedirs(path, exist_ok=True)
    return path


def prefixed(name: str, prefix: str = "") -> str:
    """Prepend *prefix* to *name* if non-empty.

    Used so each bench mode (search/rule/composite) writes its artifacts
    side-by-side in the results dir without conflicting filenames.
    """
    if not prefix:
        return name
    return f"{prefix}{name}" if prefix.endswith("_") else f"{prefix}_{name}"


def baseline_path(prefix: str = "") -> str:
    """Path to ``[prefix_]baseline.json`` in the results dir."""
    return os.path.join(results_dir(), prefixed(BASELINE_NAME, prefix))


def evolution_path(prefix: str = "") -> str:
    """Path to ``[prefix_]evolution_summary.jsonl`` in the results dir."""
    return os.path.join(results_dir(), prefixed(EVOLUTION_NAME, prefix))


def best_config_path(prefix: str = "") -> str:
    """Path to ``[prefix_]best_config.yaml`` in the results dir."""
    return os.path.join(results_dir(), prefixed(BEST_CONFIG_NAME, prefix))
