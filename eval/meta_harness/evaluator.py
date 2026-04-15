"""Inner-loop evaluator for meta-harness optimization.

Wraps existing mcp_bench and search_quality benchmarks into the
Evaluator protocol expected by the research orchestrator.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

# Ensure project root is on sys.path for eval imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from attoswarm.research.evaluator import EvalResult

from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.splits import assign_split

logger = logging.getLogger(__name__)


class CodeIntelBenchEvaluator:
    """Evaluator that scores a harness config using code-intel benchmarks.

    Combines two evaluation signals:
    1. Search quality: MRR/NDCG/P@k/R@k from ground-truth queries
    2. MCP bench: multi-category task scoring from mcp_bench suite

    The composite metric is a weighted average (0-1 scale), suitable for
    the research orchestrator's accept/reject decision.

    Implements the ``Evaluator`` protocol from attoswarm.research.evaluator.
    """

    def __init__(
        self,
        *,
        search_weight: float = 0.4,
        bench_weight: float = 0.6,
        search_repos: list[str] | None = None,
        bench_repos: list[str] | None = None,
        bench_categories: list[str] | None = None,
        split: str = "eval",
        config_filename: str = "harness_config.yaml",
    ) -> None:
        self._search_weight = search_weight
        self._bench_weight = bench_weight
        self._search_repos = search_repos  # None = all available
        self._bench_repos = bench_repos or ["express", "fastapi", "starship"]
        self._bench_categories = bench_categories  # None = all
        self._split = split
        self._config_filename = config_filename
        self._svc_cache: dict[str, Any] = {}  # repo_path -> CodeIntelService

    async def evaluate(self, working_dir: str) -> EvalResult:
        """Run benchmarks and return composite score.

        If a harness_config.yaml exists in working_dir, loads and applies it.
        Otherwise uses default scoring config.
        """
        t0 = time.monotonic()

        # Load harness config
        config_path = os.path.join(working_dir, self._config_filename)
        if os.path.isfile(config_path):
            try:
                config = HarnessConfig.load_yaml(config_path)
                errors = config.validate()
                if errors:
                    return EvalResult(
                        metric_value=0.0,
                        error=f"Invalid config: {'; '.join(errors)}",
                        success=False,
                    )
            except Exception as exc:
                return EvalResult(
                    metric_value=0.0,
                    error=f"Failed to load config: {exc}",
                    success=False,
                )
        else:
            config = HarnessConfig.default()

        # Run both evaluations (sync methods, offload to thread)
        import asyncio
        loop = asyncio.get_event_loop()
        search_result, bench_result = await asyncio.gather(
            loop.run_in_executor(None, self._run_search_quality, config),
            loop.run_in_executor(None, self._run_mcp_bench, config),
        )

        elapsed = time.monotonic() - t0

        # Compute composite
        search_score = search_result.get("composite", 0.0)
        bench_score = bench_result.get("composite", 0.0)

        total_weight = 0.0
        weighted_sum = 0.0
        if search_score is not None:
            weighted_sum += self._search_weight * search_score
            total_weight += self._search_weight
        if bench_score is not None:
            weighted_sum += self._bench_weight * bench_score
            total_weight += self._bench_weight

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0

        metadata: dict[str, Any] = {
            "search_quality": search_result,
            "mcp_bench": bench_result,
            "config": config.to_dict(),
            "elapsed_seconds": round(elapsed, 2),
        }

        return EvalResult(
            metric_value=round(composite, 4),
            raw_output=json.dumps(metadata, indent=2, default=str),
            metadata=metadata,
            metrics={
                "search_composite": search_score,
                "bench_composite": bench_score,
            },
            constraint_checks={
                "latency_ok": elapsed < 300,
            },
        )

    def _run_search_quality(self, config: HarnessConfig) -> dict[str, Any]:
        """Run search quality evaluation with the given config.

        Returns dict with per-repo metrics and composite score (0-1).
        """
        try:
            from attocode.code_intel.service import CodeIntelService

            from eval.search_quality import (
                REPO_CONFIGS,
                discover_repos_with_ground_truth,
                load_ground_truth,
                parse_search_results,
            )
            from eval.metrics import (
                compute_mrr,
                compute_ndcg,
                compute_precision_at_k,
                compute_recall_at_k,
            )
        except ImportError as exc:
            logger.warning("Search quality imports failed: %s", exc)
            return {"error": str(exc), "composite": None}

        repos = self._search_repos or discover_repos_with_ground_truth()
        if not repos:
            return {"error": "No repos with ground truth", "composite": None}

        all_mrr: list[float] = []
        all_ndcg: list[float] = []
        all_precision: list[float] = []
        all_recall: list[float] = []
        per_repo: dict[str, dict] = {}

        for repo in repos:
            repo_path = REPO_CONFIGS.get(repo)
            if not repo_path or not os.path.isdir(repo_path):
                continue

            queries = load_ground_truth(repo)
            if not queries:
                continue

            if repo_path in self._svc_cache:
                svc = self._svc_cache[repo_path]
            else:
                svc = CodeIntelService(repo_path)
                self._svc_cache[repo_path] = svc
            config.apply_to_service(svc)

            repo_mrr: list[float] = []
            repo_ndcg: list[float] = []
            repo_prec: list[float] = []
            repo_rec: list[float] = []
            query_details: list[dict] = []

            for entry in queries:
                query_text: str = entry["query"]
                relevant: list[str] = entry["relevant_files"]
                relevant_set = set(relevant)

                raw_output = svc.semantic_search(query_text)
                retrieved = parse_search_results(raw_output, max_results=20)

                mrr = compute_mrr(retrieved, relevant_set, k=10)
                ndcg = compute_ndcg(retrieved, relevant_set, k=10)
                precision = compute_precision_at_k(retrieved, relevant_set, k=10)
                recall = compute_recall_at_k(retrieved, relevant_set, k=20)

                missed = [f for f in relevant if f not in retrieved]
                query_details.append({
                    "query": query_text,
                    "mrr": round(mrr, 4),
                    "ndcg": round(ndcg, 4),
                    "recall": round(recall, 4),
                    "retrieved_top5": retrieved[:5],
                    "missed_files": missed,
                    "relevant_count": len(relevant),
                    "retrieved_relevant": len(relevant) - len(missed),
                })

                repo_mrr.append(mrr)
                repo_ndcg.append(ndcg)
                repo_prec.append(precision)
                repo_rec.append(recall)

            if repo_mrr:
                n = len(repo_mrr)
                avg_mrr = sum(repo_mrr) / n
                avg_ndcg = sum(repo_ndcg) / n
                avg_prec = sum(repo_prec) / n
                avg_rec = sum(repo_rec) / n

                per_repo[repo] = {
                    "mrr": round(avg_mrr, 4),
                    "ndcg": round(avg_ndcg, 4),
                    "precision_at_10": round(avg_prec, 4),
                    "recall_at_20": round(avg_rec, 4),
                    "queries": n,
                    "query_details": query_details,
                }

                all_mrr.append(avg_mrr)
                all_ndcg.append(avg_ndcg)
                all_precision.append(avg_prec)
                all_recall.append(avg_rec)

        if not all_mrr:
            return {"error": "No search results", "composite": None, "per_repo": per_repo}

        # Composite: weighted average of metrics (all 0-1 scale)
        avg_mrr = sum(all_mrr) / len(all_mrr)
        avg_ndcg = sum(all_ndcg) / len(all_ndcg)
        avg_prec = sum(all_precision) / len(all_precision)
        avg_rec = sum(all_recall) / len(all_recall)

        composite = 0.35 * avg_mrr + 0.30 * avg_ndcg + 0.20 * avg_rec + 0.15 * avg_prec

        return {
            "composite": round(composite, 4),
            "avg_mrr": round(avg_mrr, 4),
            "avg_ndcg": round(avg_ndcg, 4),
            "avg_precision": round(avg_prec, 4),
            "avg_recall": round(avg_rec, 4),
            "per_repo": per_repo,
        }

    def _run_mcp_bench(self, config: HarnessConfig) -> dict[str, Any]:
        """Run mcp_bench evaluation with the given config.

        Returns dict with per-category scores and composite (0-1).
        """
        try:
            from eval.mcp_bench.mcp_runner import run_benchmark
            from eval.mcp_bench.schema import BenchConfig
        except ImportError as exc:
            logger.warning("MCP bench imports failed: %s", exc)
            return {"error": str(exc), "composite": None}

        bench_config = BenchConfig(
            adapter="attocode",
            repos_filter=self._bench_repos,
            categories_filter=self._bench_categories or [],
            timeout_per_task=60.0,
        )

        try:
            suite = run_benchmark(bench_config)
        except Exception as exc:
            logger.warning("MCP bench failed: %s", exc)
            return {"error": str(exc), "composite": None}

        # Filter to eval split only
        if self._split:
            eval_results = [
                r for r in suite.task_results
                if assign_split(r.task_id) == self._split
            ]
        else:
            eval_results = suite.task_results

        if not eval_results:
            return {"error": "No eval-split results", "composite": None}

        scores = [r.score for r in eval_results if not r.error]
        if not scores:
            return {"error": "All tasks errored", "composite": None}

        # Normalize from 0-5 scale to 0-1 (clamped)
        mean_score = sum(scores) / len(scores)
        composite = min(max(mean_score / 5.0, 0.0), 1.0)

        # Per-category breakdown
        by_cat: dict[str, list[float]] = {}
        for r in eval_results:
            if not r.error:
                by_cat.setdefault(r.category, []).append(r.score)

        per_category = {
            cat: {
                "mean_score": round(sum(s) / len(s), 3),
                "count": len(s),
            }
            for cat, s in by_cat.items()
        }

        return {
            "composite": round(composite, 4),
            "mean_score_raw": round(mean_score, 3),
            "total_tasks": len(eval_results),
            "completed_tasks": len(scores),
            "per_category": per_category,
        }
