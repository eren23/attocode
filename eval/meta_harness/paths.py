"""Centralized paths for meta-harness artifacts.

Separation of concerns:
- ``configs/`` (in source tree, TRACKED): canonical reference configs for reproducibility
- Ephemeral results (gitignored under ``.attocode/meta_harness/``): per-run outputs

Override via ``ATTOCODE_META_HARNESS_RESULTS`` env var.
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


def results_dir() -> str:
    """Get the ephemeral results directory (env-overridable)."""
    return os.environ.get("ATTOCODE_META_HARNESS_RESULTS", DEFAULT_RESULTS_DIR)


def ensure_results_dir() -> str:
    """Ensure results directory exists and return its path."""
    path = results_dir()
    os.makedirs(path, exist_ok=True)
    return path
