"""Strict repair verdicts, independent of model answers and legacy graders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EVALUATOR_REVISION = "726c5461e2ef52d83cf1ea2107870a8bb3328d57"
DATASET_SHA256 = "008ac523001de665d3f1e4f4179587dcd68dd7b2f2d5bd878a5385e3e938b59d"
TEST_EXIT_MARKER = "ATTOCODE_REPAIR_TEST_EXIT"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_digest(root):
    """Include generated runtime files and links, without repository history or caches."""
    import os
    entries = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".pytest_cache"})
        for name in sorted(files + [d for d in dirs if (Path(directory) / d).is_symlink()]):
            path = Path(directory) / name
            if name.endswith(".pyc"):
                continue
            entries[path.relative_to(root).as_posix()] = (
                {"link": str(path.readlink())} if path.is_symlink() else
                {"sha256": file_hash(path), "executable": bool(path.stat().st_mode & 0o111)})
    return digest(entries)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def cached_grade(path, identity):
    if not Path(path).exists():
        return None
    cached = json.loads(Path(path).read_text())
    if cached.get("identity") != identity:
        raise ValueError("Refusing a cached evaluation for different inputs")
    return cached


def test_list(value):
    rows = json.loads(value) if isinstance(value, str) else value
    if not isinstance(rows, list) or not rows or any(not isinstance(x, str) or not x for x in rows):
        raise ValueError("A nonempty list of test IDs is required")
    if len(rows) != len(set(rows)):
        raise ValueError("Duplicate required test IDs")
    return rows


def verdict(fail_to_pass, pass_to_pass, statuses, *, exit_code, timed_out=False, executed=True):
    """Require an observed PASSED for every required ID; no silent/skip/XFAIL success."""
    f2p, p2p = test_list(fail_to_pass), test_list(pass_to_pass)
    if set(f2p) & set(p2p):
        raise ValueError("Failing and regression test sets overlap")
    required = list(dict.fromkeys(f2p + p2p))
    observed = {name: statuses.get(name, "MISSING") for name in required}
    missing = [name for name in required if name not in statuses]
    failed = [name for name, status in observed.items() if status != "PASSED"]
    resolved = bool(executed and not timed_out and exit_code == 0 and not failed)
    return {"resolved": resolved, "executed": executed, "timed_out": timed_out,
            "test_exit_code": exit_code, "required": len(required), "missing": missing,
            "failed": failed, "statuses": observed,
            "fail_to_pass": {name: observed[name] for name in f2p},
            "pass_to_pass": {name: observed[name] for name in p2p}}


def strict_script(commands, start_marker, end_marker, *, snapshot_base=None):
    """Use upstream setup/test command, with test patches applied separately and checked.

    The pinned Python spec has exactly one test command between its markers.
    Capture that command's status before cleanup can replace it.
    """
    starts = [i for i, line in enumerate(commands) if line == f": '{start_marker}'"]
    ends = [i for i, line in enumerate(commands) if line == f": '{end_marker}'"]
    if len(starts) != 1 or len(ends) != 1 or ends[0] != starts[0] + 2:
        raise ValueError("Unsupported evaluator script: expected one delimited test command")
    start = starts[0]
    # The two commands before START restore tests and apply the official patch.
    # The worker already performed both with checked exit statuses.
    if start < 2 or "git apply" not in commands[start - 1] or "git checkout" not in commands[start - 2]:
        raise ValueError("Pinned test-patch setup changed")
    prefix = list(commands[:start - 2])
    if snapshot_base:
        # Snapshots deliberately have fresh history. These are diagnostics, not tests.
        prefix = ["git show --stat --oneline HEAD" if line == "git show" else
                  "git -c core.fileMode=false diff HEAD" if line == "git -c core.fileMode=false diff " + snapshot_base
                  else line for line in prefix]
    lines = ["#!/bin/bash", "set -euxo pipefail", *prefix,
             f": '{start_marker}'", "set +e", "(", commands[start + 1], ")",
             "repair_test_rc=$?", f"printf '\\n{TEST_EXIT_MARKER}=%s\\n' \"$repair_test_rc\"",
             f": '{end_marker}'", 'exit "$repair_test_rc"']
    return "\n".join(lines) + "\n"


def gate(rows, expected=32):
    """Outcome-first development gate. Adoption is reported, never a prerequisite."""
    import statistics
    from collections import Counter

    pairs = Counter((r["task"], r["lane"]) for r in rows)
    complete = (len(rows) == expected and len({r["id"] for r in rows}) == expected
                and len(pairs) == 16 and all(n == 2 for n in pairs.values())
                and {r["lane"] for r in rows} == {"native", "lean_optional"}
                and all(r.get("protocol_status") == "clear" and r.get("grade") is not None for r in rows))
    result = {"complete": complete, "decision": "inconclusive", "adoption_is_gate": False}
    if not complete:
        return result
    arms = {a: [r for r in rows if r["lane"] == a] for a in ("native", "lean_optional")}
    if {r["task"] for r in arms["native"]} != {r["task"] for r in arms["lean_optional"]}:
        return result
    score = {a: statistics.fmean(bool(r["grade"]["resolved"]) for r in rs) for a, rs in arms.items()}
    known_costs = [r.get("cost_usd") for r in rows if isinstance(r.get("cost_usd"), (int, float))]
    if not known_costs or any(r.get("cost_usd") is None and r.get("status") == "completed" for r in rows):
        return {**result, "resolution": score, "reason": "Cost estimates unavailable"}
    worst = max(known_costs)
    cost = {a: statistics.fmean(worst if r.get("cost_usd") is None else r["cost_usd"] for r in rs)
            for a, rs in arms.items()}
    times = {a: statistics.fmean(r["seconds"] if r["grade"]["resolved"] else 600 for r in rs)
             for a, rs in arms.items()}
    delta = score["lean_optional"] - score["native"]
    if not cost["native"] or not times["native"]:
        return {**result, "resolution": score, "reason": "Undefined baseline ratio"}
    cr, tr = cost["lean_optional"] / cost["native"], times["lean_optional"] / times["native"]
    result.update(resolution=score, delta=delta, cost_ratio=cr, time_ratio=tr,
                  imputed_costs=sum(r.get("cost_usd") is None for r in rows),
                  substantive_adoption=sum(bool(r.get("substantive_adoption")) for r in arms["lean_optional"]),
                  decision="advance" if delta >= .125 and cr <= 1.25 and tr <= 1.25 else "stop")
    return result
