"""Deterministic train/eval split for benchmark tasks.

Uses a hash of task_id to assign each task to train or eval split,
ensuring reproducibility without manual annotation.
"""

from __future__ import annotations

import hashlib


def assign_split(task_id: str, eval_ratio: float = 0.3, seed: int = 42) -> str:
    """Assign a task to 'train' or 'eval' split deterministically.

    Uses MD5 hash of (seed, task_id) modulo 100 to decide.

    Args:
        task_id: Unique task identifier.
        eval_ratio: Fraction of tasks assigned to eval (default 0.3).
        seed: Hash seed for reproducibility.

    Returns:
        "train" or "eval".
    """
    h = hashlib.md5(f"{seed}:{task_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) % 100
    return "eval" if bucket < int(eval_ratio * 100) else "train"


def split_tasks(tasks: list, eval_ratio: float = 0.3, seed: int = 42) -> dict[str, list]:
    """Split a list of tasks (with .task_id attribute) into train/eval sets.

    Returns:
        Dict with "train" and "eval" keys mapping to task lists.
    """
    result: dict[str, list] = {"train": [], "eval": []}
    for task in tasks:
        s = assign_split(task.task_id, eval_ratio, seed)
        result[s].append(task)
    return result
