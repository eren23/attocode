"""Fail-closed release checks for complete, revision-bound paired client evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
from pathlib import Path
from urllib.request import urlopen

CLIENTS = ("codex", "claude", "cursor")
REPOS = ("fastapi", "express", "frontend", "ripgrep")
FAMILIES = ("lookup", "change", "returning")
LANES = ("native", "intel_base", "intel_precision", "serena")


def engine_hash(project):
    digest = hashlib.sha256()
    root = project / "packages/code-intel/src"
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def interval(gains, seed=7329):
    """Hierarchical paired bootstrap: repositories first, repetitions second."""
    rng = random.Random(seed)
    repos = sorted(gains)
    estimates = []
    for _ in range(2000):
        sample = []
        for repo in rng.choices(repos, k=len(repos)):
            sample.extend(rng.choices(gains[repo], k=len(gains[repo])))
        estimates.append(statistics.median(sample))
    estimates.sort()
    return [estimates[49], estimates[1949]]


def evaluate(report, expected_engine):
    reasons, groups = [], []
    manifest = report.get("manifest", {})
    if manifest.get("mode", "release") != "release":
        reasons.append("Pilot reports are development evidence and cannot authorize a release")
    recorded_id = manifest.get("study_id")
    unsigned = {key: value for key, value in manifest.items() if key != "study_id"}
    if recorded_id != hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
        reasons.append("Study manifest fingerprint is invalid")
    if manifest.get("engine_sha256") != expected_engine:
        reasons.append("Evidence engine does not match this candidate")
    if manifest.get("selection") != "natural" or manifest.get("repetitions") != 5:
        reasons.append("Release evidence requires natural tool selection and five repetitions")
    if any(manifest.get("client_versions", {}).get(client) in {None, "unavailable"} for client in CLIENTS):
        reasons.append("All three client versions must be recorded")
    expected = {f"{repo}:{family}:{client}:{repeat}:{lane}"
                for repo in REPOS for family in FAMILIES for client in CLIENTS for repeat in range(5) for lane in LANES}
    runs = report.get("runs", [])
    rows = {row.get("id"): row for row in runs}
    if len(rows) != len(runs) or set(rows) != expected:
        reasons.append(f"Need exactly 720 distinct runs; found {len(rows)}, missing {len(expected - set(rows))}")
    for row in runs:
        identity = f"{row.get('task')}:{row.get('client')}:{row.get('repeat')}:{row.get('lane')}"
        if (row.get("id") != identity or row.get("study_id") != manifest.get("study_id") or row.get("status") != "completed"
                or row.get("model") != manifest.get("models", {}).get(row.get("client"))
                or not isinstance(row.get("passed"), bool)
                or not isinstance(row.get("seconds"), (int, float))
                or not math.isfinite(row["seconds"]) or row["seconds"] <= 0):
            reasons.append("Run identity, completion, model or timing is invalid")
            break
    if not reasons:
        timeout = manifest.get("timeout", 600)
        for client in CLIENTS:
            for family in FAMILIES:
                for intel in ("intel_base", "intel_precision"):
                    for comparator in ("native", "serena"):
                        gains, successes, quality = {}, [0, 0], True
                        for repo in REPOS:
                            gains[repo] = []
                            case_successes = [0, 0]
                            for repeat in range(5):
                                a = rows[f"{repo}:{family}:{client}:{repeat}:{intel}"]
                                b = rows[f"{repo}:{family}:{client}:{repeat}:{comparator}"]
                                successes[0] += a["passed"]
                                successes[1] += b["passed"]
                                case_successes[0] += a["passed"]
                                case_successes[1] += b["passed"]
                                penalty = timeout * (2 if family == "returning" else 1)
                                a_seconds = a["seconds"] if a["passed"] else max(a["seconds"], penalty)
                                b_seconds = b["seconds"] if b["passed"] else max(b["seconds"], penalty)
                                gains[repo].append(1 - a_seconds / b_seconds)
                            quality &= case_successes[0] >= case_successes[1] and case_successes[0] > 0
                        median = statistics.median(value for values in gains.values() for value in values)
                        bounds = interval(gains)
                        passed = quality and median >= .20 and bounds[0] > 0
                        groups.append({"client": client, "family": family, "lane": intel, "comparator": comparator,
                                       "median_paired_speedup": median, "ci95": bounds,
                                       "successes": successes, "pairs": 20, "passed": passed})
        if not all(group["passed"] for group in groups):
            reasons.append("One or more client/workflow comparisons failed quality or speed criteria")
    volume = report.get("response_volume", {})
    volume_rows = volume.get("rows", [])
    volume_expected = {f"{client}:{repo}:{query}" for client in CLIENTS for repo in REPOS for query in range(5)}
    volume_ids = {row.get("id") for row in volume_rows}
    if (volume.get("measurement") != "client_visible" or volume.get("candidate_engine_sha256") != expected_engine
            or not volume.get("baseline_engine_sha256") or len(volume_rows) != len(volume_ids)
            or volume_ids != volume_expected):
        reasons.append("Missing complete matched-query volume evidence from all three clients")
    else:
        for client in CLIENTS:
            values = [row for row in volume_rows if row["id"].startswith(client + ":")]
            valid = all(row.get("evidence_preserved") is True and isinstance(row.get("before"), int)
                        and isinstance(row.get("after"), int) and row["before"] > 0 and row["after"] > 0 for row in values)
            if not valid or statistics.median(1 - row["after"] / row["before"] for row in values) < .40:
                reasons.append(f"{client}: response volume reduction is below 40% or evidence is missing")
    return {"passed": not reasons, "reasons": reasons, "groups": groups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--download", action="store_true", help="Use pinned INTELLIGENCE_EVIDENCE_URL/SHA256 environment variables")
    args = parser.parse_args()
    if args.download:
        url, expected = os.environ.get("INTELLIGENCE_EVIDENCE_URL", ""), os.environ.get("INTELLIGENCE_EVIDENCE_SHA256", "")
        if not url.startswith("https://") or len(expected) != 64:
            raise SystemExit("Release blocked: configure a complete performance report URL and SHA256")
        with urlopen(url, timeout=60) as response:
            content = response.read(20_000_001)
        if len(content) > 20_000_000 or hashlib.sha256(content).hexdigest() != expected:
            raise SystemExit("Release blocked: performance report size or SHA256 mismatch")
        report = json.loads(content)
    elif args.report:
        report = json.loads(args.report.read_text())
    else:
        parser.error("Supply --report or --download")
    result = evaluate(report, engine_hash(args.project))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
