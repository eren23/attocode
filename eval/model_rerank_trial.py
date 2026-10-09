"""Offline-first, paired reranker trial on frozen code-navigation candidate pools.

The input is a JSON result from ``eval.ranking_pair``. Its ``prior`` file order
is the candidate pool for every arm; this script never reindexes or writes to
the benchmark repositories. Gold files are narrow target judgments, not an
exhaustive list of relevant files.

Example:
    PYTHONPATH=packages/code-intel/src .venv/bin/python -m eval.model_rerank_trial \
      --pool /private/tmp/attocode-ranking-final-holdout.json \
      --model minilm --max-candidates 12 --output /private/tmp/minilm-trial.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from attocode_intel.focused_evidence import file_excerpt

from eval.metrics import compute_mrr, compute_ndcg, compute_recall_at_k

MINILM_CACHE = Path.home() / ".cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/snapshots"
QWEN_LOCAL = Path("/private/tmp/attocode-qwen3-reranker-06b")
DECISION_LOCAL = Path("/private/tmp/attocode-decision2-kai-06b")
GTE_LOCAL = Path("/private/tmp/attocode-gte-modernbert-reranker")
INSTRUCTION = (
    "Find implementation files that help a developer investigate the code-navigation query. "
    "Prefer behavioral evidence over incidental keyword overlap."
)
DECISION_QUESTION = {
    "p": {
        "type": "noul",
        "instructions": "Does this file contain implementation evidence needed to investigate the query?",
        "criteria": {
            "true": "The file implements or directly configures the requested behavior.",
            "false": "Only incidental word overlap, unrelated code, or tests/docs without implementation.",
        },
    },
}


def _revision(root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                            capture_output=True, check=True, timeout=5)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                            cwd=root, text=True, capture_output=True, check=True, timeout=5)
    if status.stdout.strip():
        raise ValueError(f"Tracked source files changed: {root}")
    return result.stdout.strip()


def _excerpt(root: Path, relative: str, query: str) -> str:
    """Select the same bounded, query-focused file evidence for every model."""
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Candidate is missing or outside repository: {relative}")
    return file_excerpt(target.read_text(errors="replace").splitlines(), relative, query)


def _metrics(files: list[str], gold: list[str]) -> dict:
    target = set(gold)
    return {
        "mrr5": compute_mrr(files, target, 5),
        "ndcg5": compute_ndcg(files, target, 5),
        "recall5": compute_recall_at_k(files, target, 5),
        "mrr10": compute_mrr(files, target, 10),
        "recall20": compute_recall_at_k(files, target, 20),
    }


def _load_model(name: str):
    if name == "decision2":
        from decision2 import Decision2

        if not (DECISION_LOCAL / "MODEL_MANIFEST.json").is_file():
            raise FileNotFoundError(f"Local Decision 2.0 Kai not found: {DECISION_LOCAL}")
        started = time.perf_counter()
        model = Decision2.from_pretrained(DECISION_LOCAL, device="cpu", threads=4)
        return model, str(DECISION_LOCAL), round((time.perf_counter() - started) * 1000, 1)

    from sentence_transformers import CrossEncoder

    if name == "minilm":
        paths = sorted(MINILM_CACHE.iterdir()) if MINILM_CACHE.is_dir() else []
        if not paths:
            raise FileNotFoundError("Cached MiniLM cross-encoder not found")
        path = paths[0]
    elif name == "qwen3":
        path = QWEN_LOCAL
        if not (path / "config.json").is_file():
            raise FileNotFoundError(f"Local Qwen3 reranker not found: {path}")
    elif name == "gte":
        path = GTE_LOCAL
        if not (path / "config.json").is_file():
            raise FileNotFoundError(f"Local GTE ModernBERT reranker not found: {path}")
    else:
        raise ValueError(name)
    kwargs = {"max_length": 384 if name == "qwen3" else 512,
              "local_files_only": True, "trust_remote_code": False}
    started = time.perf_counter()
    model = CrossEncoder(str(path), **kwargs)
    if name == "qwen3":
        if model.tokenizer.pad_token_id is None:
            model.tokenizer.pad_token = model.tokenizer.eos_token
        model.model.config.pad_token_id = model.tokenizer.pad_token_id
    return model, str(path), round((time.perf_counter() - started) * 1000, 1)


def _jev_scores(query: str, paths: list[str], evidence: list[str]) -> tuple[list[float], int]:
    """Bounded remote trial; never silently converts an outage into a win."""
    from attocode_intel.confidence.jev import _decide
    from attocode_intel.confidence.redact import redact
    from dotenv import dotenv_values

    key = os.environ.get("OPENROUTER_API_KEY") or dotenv_values(Path.home() / ".jev/env").get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Jev trial needs an OpenRouter key")
    os.environ["OPENROUTER_API_KEY"] = key
    def ask(item: tuple[int, str, str]) -> float | None:
        index, path, excerpt = item
        try:
            result = _decide(
                "attocode_search_rerank_trial",
                {"query": redact(query), "file": redact(path), "code": redact(excerpt)},
                DECISION_QUESTION, "yes" if index < 5 else "no", "openrouter",
            )
            value = ((result.get("answers") or {}).get("p") or {}).get("noul")
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            return float(value) if math.isfinite(value) and 0 <= value <= 1 else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(pool.map(ask, ((i, path, excerpt)
                                      for i, (path, excerpt) in enumerate(zip(paths, evidence, strict=True)))))
    failures = sum(score is None for score in answers)
    return [score if score is not None else 0.5 for score in answers], failures


def _decision_scores(model, query: str, paths: list[str], evidence: list[str]) -> tuple[list[float], int]:
    scores = []
    for path, excerpt in zip(paths, evidence, strict=True):
        try:
            result = model.system_one(
                state={"query": query, "file": path, "code": excerpt},
                questions=DECISION_QUESTION,
            )
            value = ((result.get("answers") or {}).get("p") or {}).get("noul")
            valid = isinstance(value, int | float) and not isinstance(value, bool)
            scores.append(float(value) if valid and math.isfinite(value) and 0 <= value <= 1 else None)
        except Exception:
            scores.append(None)
    failures = sum(score is None for score in scores)
    return [score if score is not None else 0.5 for score in scores], failures


def _choice_scores(model, query: str, paths: list[str], evidence: list[str],
                   *, remote: bool) -> tuple[list[float], int]:
    """One typed choice over the candidate page, with a full probability ranking."""
    criteria = {str(i): excerpt for i, excerpt in enumerate(evidence)}
    question = {
        "best": {
            "type": "choice",
            "instructions": "Which source file most directly implements the behavior in the query?",
            "criteria": criteria,
        },
    }
    state = {"query": query, "task": "Find the primary implementation file, not an incidental match."}
    try:
        if remote:
            from attocode_intel.confidence.jev import _decide
            from attocode_intel.confidence.redact import redact
            from dotenv import dotenv_values

            key = os.environ.get("OPENROUTER_API_KEY") or dotenv_values(Path.home() / ".jev/env").get("OPENROUTER_API_KEY")
            if not key:
                raise RuntimeError("Jev trial needs an OpenRouter key")
            os.environ["OPENROUTER_API_KEY"] = key
            safe_state = {name: redact(value) for name, value in state.items()}
            safe_criteria = {name: redact(value) for name, value in criteria.items()}
            result = _decide("attocode_search_choice_trial", safe_state,
                             {"best": {**question["best"], "criteria": safe_criteria}},
                             "0", "openrouter")
        else:
            result = model.system_one(state=state, questions=question)
        probs = ((result.get("answers") or {}).get("best") or {}).get("probabilities")
        if not isinstance(probs, dict):
            raise ValueError("No choice probabilities returned")
        scores = [probs.get(str(i)) for i in range(len(paths))]
        if any(isinstance(value, bool) or not isinstance(value, int | float)
               or not math.isfinite(value) or not 0 <= value <= 1 for value in scores):
            raise ValueError("Invalid choice probabilities")
        return [float(value) for value in scores], 0
    except Exception:
        return [0.5] * len(paths), len(paths)


def _systemone_http_scores(ranker, query: str, paths: list[str],
                           evidence: list[str]) -> tuple[list[float], int, str | None]:
    """Exercise the production adapter against the same frozen evidence."""
    candidates = [(str(index), excerpt, float(len(paths) - index))
                  for index, excerpt in enumerate(evidence)]
    with ranker._inflight:  # wait out an earlier timed-out call; trials run one query at a time
        pass
    outcome = ranker.rerank_result(query, candidates, top_k=len(candidates))
    if not outcome.reranked:
        return [0.5] * len(paths), len(paths), outcome.fallback_reason
    scores = {candidate_id: score for candidate_id, _excerpt, score in outcome.candidates}
    return [scores[str(index)] for index in range(len(paths))], 0, None


def _select(pool: dict, selections: set[str], repo_names: set[str] | None = None) -> list[tuple[dict, dict]]:
    repo_names = repo_names or set()
    unknown = repo_names - {repo["repo"] for repo in pool["repos"]}
    if unknown:
        raise ValueError(f"Repositories absent from pool: {sorted(unknown)}")
    rows = []
    for repo in pool["repos"]:
        if repo_names and repo["repo"] not in repo_names:
            continue
        for case in repo["queries"]:
            key = f"{repo['repo']}::{case['query']}"
            if not selections or key in selections:
                rows.append((repo, case))
    missing = selections - {f"{repo['repo']}::{case['query']}" for repo, case in rows}
    if missing:
        raise ValueError(f"Selections absent from pool: {sorted(missing)}")
    return rows


def run(pool_path: Path, *, model_name: str, selections: set[str],
        max_candidates: int, allow_remote: bool = False,
        repo_names: set[str] | None = None, endpoint: str = "", model_id: str = "",
        auth_env: str = "", timeout_ms: int = 0, max_query_chars: int = 0) -> dict:
    if max_candidates < 2:
        raise ValueError("max_candidates must be at least 2")
    pool_bytes = pool_path.read_bytes()
    pool = json.loads(pool_bytes)
    cases = _select(pool, selections, repo_names)
    if not cases:
        raise ValueError("No cases selected")
    prepared = []
    for repo, case in cases:
        root = Path(repo["source"]).resolve()
        if _revision(root) != repo["source_revision"]:
            raise ValueError(f"Repository revision changed: {repo['repo']}")
        files = case["arms"]["prior"]["files"][:max_candidates]
        if len(files) != len(set(files)):
            raise ValueError("Expected unique file candidates")
        evidence = [_excerpt(root, path, case["query"]) for path in files]
        prepared.append((repo["repo"], case, files, evidence))
    ranker = None
    if model_name == "systemone-http":
        from attocode_intel._internal.integrations.context.systemone_ranker import (
            SystemOneChoiceReranker,
        )

        ranker = SystemOneChoiceReranker(
            endpoint, model=model_id, auth_env=auth_env, allow_remote=allow_remote,
            max_candidates=max_candidates,
            timeout_seconds=None if timeout_ms == 0 else timeout_ms / 1000,
        )
        model, model_path, load_ms = None, model_id or "unspecified-server-model", 0.0
    elif model_name in {"jev", "jev-choice"}:
        if not allow_remote:
            raise ValueError("Jev sends source excerpts to OpenRouter; pass --allow-remote")
        model, model_path, load_ms = None, "typesafe/jev-1.13 via OpenRouter", 0.0
    else:
        model, model_path, load_ms = _load_model(
            "decision2" if model_name == "decision2-choice" else model_name)
    output = {
        "model": model_name, "model_path": model_path, "model_load_ms": load_ms,
        "pool": str(pool_path), "pool_sha256": hashlib.sha256(pool_bytes).hexdigest(),
        "max_candidates": max_candidates, "max_query_chars": max_query_chars or None, "instruction": INSTRUCTION if model_name == "qwen3" else None,
        "adapter": "systemone-choice-v1" if model_name == "systemone-http" else None,
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest()
        if model_name == "systemone-http" else None,
        "timeout_ms": round(ranker.timeout_seconds * 1000)
        if model_name == "systemone-http" else None,
        "cases": [],
    }
    for repo_name, case, files, evidence in prepared:
        started = time.perf_counter()
        fallback_reason = None
        if model_name == "systemone-http":
            scores, failures, fallback_reason = _systemone_http_scores(
                ranker, case["query"], files, evidence)
        elif model_name == "jev":
            scores, failures = _jev_scores(case["query"], files, evidence)
        elif model_name == "decision2":
            scores, failures = _decision_scores(model, case["query"], files, evidence)
        elif model_name in {"decision2-choice", "jev-choice"}:
            # The product sends query[:512] to its ranker; excerpts still use the whole query.
            query = case["query"][:max_query_chars] if max_query_chars else case["query"]
            scores, failures = _choice_scores(model, query, files, evidence,
                                              remote=model_name == "jev-choice")
            if failures:  # every candidate scored 0.5, so the case keeps the lexical order
                fallback_reason = "request_failed"
        else:
            query_text = (INSTRUCTION + "\nQuery: " + case["query"]
                          if model_name == "qwen3" else case["query"])
            scores = model.predict([(query_text, text) for text in evidence],
                                   batch_size=1 if model_name == "qwen3" else 8,
                                   show_progress_bar=False)
            failures = 0
        elapsed_ms = (time.perf_counter() - started) * 1000
        scored = [(float(score), index) for index, score in enumerate(scores)]
        order = [index for _score, index in sorted(scored, key=lambda row: (-row[0], row[1]))]
        ranked = [files[index] for index in order]
        baseline = _metrics(files, case["gold"])
        treatment = _metrics(ranked, case["gold"])
        row = {
            "repo": repo_name, "query": case["query"], "gold": case["gold"],
            "candidate_count": len(files), "baseline_files": files,
            "ranked_files": ranked, "scores": [round(float(score), 5) for score in scores],
            "evidence_sha256": hashlib.sha256("\n".join(evidence).encode()).hexdigest(),
            "baseline": baseline, "treatment": treatment, "inference_ms": round(elapsed_ms, 1),
            "failures": failures,
            "fallback_reason": fallback_reason,
        }
        output["cases"].append(row)
        print(json.dumps({"repo": repo_name, "query": case["query"],
                          "mrr5": [baseline["mrr5"], treatment["mrr5"]],
                          "ms": row["inference_ms"]}), flush=True)
    latencies = sorted(r["inference_ms"] for r in output["cases"])
    output["summary"] = {
        "cases": len(output["cases"]),
        "median_inference_ms": round(statistics.median(latencies), 1),
        "p95_inference_ms": latencies[math.ceil(0.95 * len(latencies)) - 1],
        "cost_usd": None,  # Not reported by all providers; do not infer zero cost.
        "failures": sum(r["failures"] for r in output["cases"]),
        "metrics": {},
    }
    for metric in ("mrr5", "ndcg5", "recall5", "mrr10", "recall20"):
        before = [r["baseline"][metric] for r in output["cases"]]
        after = [r["treatment"][metric] for r in output["cases"]]
        output["summary"]["metrics"][metric] = {
            "baseline": round(statistics.mean(before), 4),
            "model": round(statistics.mean(after), 4),
            "wins": sum(b > a + 1e-9 for a, b in zip(before, after, strict=True)),
            "losses": sum(b < a - 1e-9 for a, b in zip(before, after, strict=True)),
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--model", choices=("minilm", "gte", "qwen3", "decision2",
                                            "decision2-choice", "jev", "jev-choice",
                                            "systemone-http"), required=True)
    parser.add_argument("--select", action="append", default=[],
                        help="Repo and query, e.g. 'starship::config loading'; repeatable")
    parser.add_argument("--repo", action="append", default=[],
                        help="Select every case for this repository; repeatable")
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--allow-remote", action="store_true",
                        help="Allow sending bounded source excerpts to a remote model endpoint")
    parser.add_argument("--endpoint", default="", help="Explicit POST URL for systemone-http")
    parser.add_argument("--model-id", default="", help="Model ID, if the endpoint requires one")
    parser.add_argument("--auth-env", default="", help="Environment variable holding a bearer token")
    parser.add_argument("--timeout-ms", type=int, default=0,
                        help="Whole-call limit; 0 uses 5s loopback or 800ms remote")
    parser.add_argument("--max-query-chars", type=int, default=0,
                        help="Cut the query sent to a choice model to this many characters; 0 sends all")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.pool, model_name=args.model, selections=set(args.select),
                 max_candidates=args.max_candidates, allow_remote=args.allow_remote,
                 repo_names=set(args.repo), endpoint=args.endpoint, model_id=args.model_id,
                 auth_env=args.auth_env, timeout_ms=args.timeout_ms,
                 max_query_chars=args.max_query_chars)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"summary": result["summary"]}), flush=True)


if __name__ == "__main__":
    main()
