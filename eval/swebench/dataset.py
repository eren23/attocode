"""Download, cache, and convert SWE-bench Lite to BenchInstance.

Supports loading from:
- Local JSONL file (same format as eval/runner.py)
- HuggingFace datasets (princeton-nlp/SWE-bench_Lite)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from eval.harness import BenchInstance

# Default cache directory
CACHE_DIR = os.path.expanduser("~/.cache/attocode/swebench")

# SWE-bench Lite has 300 instances
SWEBENCH_LITE_SIZE = 300


def load_from_jsonl(
    path: str,
    *,
    limit: int | None = None,
    instance_ids: list[str] | None = None,
) -> list[BenchInstance]:
    """Load SWE-bench instances from a JSONL file.

    Expected fields per line:
        instance_id, repo, base_commit, problem_statement,
        patch (gold), test_patch, hints_text, version,
        FAIL_TO_PASS, PASS_TO_PASS
    """
    instances: list[BenchInstance] = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)

            if instance_ids and data["instance_id"] not in instance_ids:
                continue

            instances.append(_data_to_bench_instance(data))

            if limit and len(instances) >= limit:
                break

    return instances


def load_from_huggingface(
    *,
    split: str = "test",
    limit: int | None = None,
    instance_ids: list[str] | None = None,
    cache_dir: str = CACHE_DIR,
) -> list[BenchInstance]:
    """Load SWE-bench Lite from HuggingFace datasets.

    Requires: pip install datasets
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError(
            "HuggingFace datasets not installed. "
            "Run: pip install datasets\n"
            "Or provide a local JSONL file instead."
        )

    os.makedirs(cache_dir, exist_ok=True)

    ds = load_dataset(
        "princeton-nlp/SWE-bench_Lite",
        split=split,
        cache_dir=cache_dir,
    )

    instances: list[BenchInstance] = []
    for row in ds:
        if instance_ids and row["instance_id"] not in instance_ids:
            continue

        instances.append(_data_to_bench_instance(row))

        if limit and len(instances) >= limit:
            break

    return instances


def _data_to_bench_instance(data: dict[str, Any]) -> BenchInstance:
    """Convert a raw data dict to BenchInstance."""
    # Parse FAIL_TO_PASS / PASS_TO_PASS if present
    fail_to_pass = data.get("FAIL_TO_PASS", "")
    if isinstance(fail_to_pass, list):
        fail_to_pass = json.dumps(fail_to_pass)

    pass_to_pass = data.get("PASS_TO_PASS", "")
    if isinstance(pass_to_pass, list):
        pass_to_pass = json.dumps(pass_to_pass)

    return BenchInstance(
        instance_id=data["instance_id"],
        repo=data.get("repo", ""),
        base_commit=data.get("base_commit", ""),
        problem_statement=data.get("problem_statement", ""),
        patch_gold=data.get("patch", ""),
        test_patch=data.get("test_patch", ""),
        hints=data.get("hints_text", ""),
        metadata={
            "version": data.get("version", ""),
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
            "created_at": data.get("created_at", ""),
        },
    )


def get_instance_repo_url(instance: BenchInstance) -> str:
    """Convert repo field (e.g. 'django/django') to clone URL."""
    repo = instance.repo
    if repo.startswith("http") or repo.startswith("git@"):
        return repo
    return f"https://github.com/{repo}.git"
