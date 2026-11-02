"""Search observations from real compact MCP delivery, including output budgeting.

The historical search_usefulness trial remains an engine-level replay. This
operator measures a fresh gateway; labels are source-bound, non-exhaustive and
implementer-authored, not independent user or agent outcomes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from attocode_intel.gateway import OperationGateway
from attocode_intel.service import CodeIntelService

from eval.quality.runner import REPO, fingerprint


def engine_identity():
    import attocode_intel

    root = Path(attocode_intel.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def evidence_hits(results, evidence):
    """File presence, enclosing ranges and literal visible quotes are separate."""
    return {
        "files": [i for i, e in enumerate(evidence)
                  if any(r.get("file_path") == e["file"] for r in results)],
        "ranges": [i for i, e in enumerate(evidence) if any(
            r.get("file_path") == e["file"] and 0 < (r.get("line") or 0) <= e["line"] <= (r.get("end_line") or 0)
            for r in results)],
        "visible": [i for i, e in enumerate(evidence) if any(
            r.get("file_path") == e["file"] and e["quote"] in r.get("snippet", "")
            and 0 < (r.get("snippet_start_line") or 0) <= e["line"] <= (r.get("snippet_end_line") or 0)
            for r in results)],
    }


def decode(response):
    if response.isError:
        raise RuntimeError(str(response.content))
    payload = json.loads(response.content[0].text)
    if "data" not in payload or payload["data"].get("error"):
        raise RuntimeError(str(payload))
    return payload


async def observe(gateway, query, *, top_k, budget, mode="auto", file_filter="", capture_generation=False):
    """Execute the public gateway, recording diagnostics without replacing it."""
    before_hydration = []
    generation = []
    rankings = []
    rank = CodeIntelService._rank_search_results

    def record(service, *args, **kwargs):
        results, ranking = rank(service, *args, **kwargs)
        before_hydration.extend({"file_path": r.file_path, "name": r.name, "chunk_type": r.chunk_type,
                                 "line": r.start_line, "end_line": r.end_line} for r in results)
        rankings.append(json.loads(json.dumps(ranking, default=str)))
        return results, ranking

    request = {"query": query, "top_k": top_k, "max_tokens": budget, "mode": mode, "file_filter": file_filter}
    started = time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(patch.object(CodeIntelService, "_rank_search_results", record))
        if capture_generation:
            from attocode_intel._internal.integrations.context.semantic_search import (
                SemanticSearchManager,
            )

            for method, stage in (("_keyword_search", "keyword"), ("_body_search", "body"), ("_file_search", "file_bm25")):
                original = getattr(SemanticSearchManager, method)

                def capture(manager, *args, _fn=original, _stage=stage, **kwargs):
                    rows = _fn(manager, *args, **kwargs)
                    generation.append({"stage": _stage, "arguments": list(args), "keywords": kwargs,
                                       "results": [r if isinstance(r, str) else {
                                           "file": r.file_path, "name": r.name, "kind": r.chunk_type, "score": r.score,
                                           "start": r.start_line, "end": r.end_line,
                                           "definition_start": r.definition_start_line, "definition_end": r.definition_end_line,
                                           "text_sha256": hashlib.sha256(r.text.encode()).hexdigest()} for r in rows]})
                    return rows

                stack.enter_context(patch.object(SemanticSearchManager, method, capture))
        payload = decode(await gateway.execute_mcp("semantic_search", request))
    seconds = time.perf_counter() - started
    data = payload["data"]
    index = data.get("ranking", {}).get("index", {})
    if index.get("status") != "ready":
        raise RuntimeError(f"Incomplete search index: {index}")
    # Store the entire delivered envelope: trimming may remove metadata too.
    result = {"request": request, "response": payload, "seconds": seconds,
              "pre_hydration_diagnostic": before_hydration, "ranking_diagnostic": rankings}
    if capture_generation:
        result["generation_diagnostic"] = generation
    return result


async def inspect_first_named(gateway, results, query, budget):
    """A fixed navigation policy; never choose a result using the answer labels."""
    hit = next((h for h in results if h.get("chunk_type") in {"function", "method", "class"}
                and h.get("name") and h.get("line")), None)
    if hit is None:
        return None
    request = {"symbol_name": hit["name"], "file_path": hit["file_path"], "line": hit["line"],
               "task_hint": query, "max_tokens": budget}
    return {"request": request, "response": decode(await gateway.execute_mcp("inspect_symbol", request))}


def embed_diagnostic(mgr, query="load settings from a configuration file"):
    """Store and cosine facts for a failed dense preflight; one extra query embedding."""
    out = {}
    try:
        import numpy as np
        from attocode_intel._internal.integrations.context import vector_store

        store = mgr._store
        conn = store._get_conn()
        with store._lock:
            rows = conn.execute("SELECT length(vector), dimension, model_name, COUNT(*) "
                                "FROM vectors GROUP BY 1, 2, 3").fetchall()
        out |= {"store": id(store), "db": str(store.db_path), "dimension": store.dimension,
                "degraded": getattr(store, "degraded", None), "count": store.count(),
                "numpy": vector_store._HAS_NUMPY, "rows": rows}
        qvec = mgr._provider.embed_query([query])[0]
        out["qvec"] = {"len": len(qvec), "norm": float(np.linalg.norm(qvec)) if qvec else 0.0,
                       "head": [round(float(x), 4) for x in qvec[:4]]}
        out["search"] = [(h.file_path, h.score) for h in store.search(qvec, top_k=5)] if qvec else None
        m = store._vec_matrix
        out["matrix"] = {"shape": None if m is None else list(m.shape), "meta": len(store._vec_meta or []),
                         "loaded": store._vec_loaded_version, "version": store._vec_cache_version}
        if m is not None and len(m) and qvec:
            s = m @ np.asarray(qvec, dtype=np.float32)
            out["cosine"] = {"max": float(np.nanmax(s)), "min": float(np.nanmin(s)), "mean": float(np.nanmean(s)),
                             "positive": int((s > 0).sum()), "nan": int(np.isnan(s).sum()),
                             "row0_norm": float(np.linalg.norm(m[0]))}
            out["self"] = [(h.file_path, h.score) for h in store.search(m[0].tolist(), top_k=1)]
        return out
    except Exception as exc:  # the diagnostic must not hide the preflight failure
        return {**out, "diagnostic_error": repr(exc)}


def inspect_hits(inspection, evidence):
    if not inspection:
        return []
    data = inspection["response"]["data"]
    definition = data.get("definition", {})
    excerpts = [data.get("source", {}), *data.get("source_excerpts", [])]
    return [i for i, e in enumerate(evidence) if definition.get("file_path") == e["file"] and any(
        e["quote"] in x.get("text", "") and 0 < x.get("start_line", 0) <= e["line"] <= x.get("end_line", 0)
        for x in excerpts)]


def worst_of(samples):
    """Labels every sample delivered; a nondeterministic ranker gets no lucky draw."""
    return {metric: sorted(set.intersection(*(set(s["hits"][metric]) for s in samples)))
            for metric in samples[0]["hits"]}


def summarize(rows):
    summary = {"questions": len(rows)}
    for page in ("5", "24", "scoped"):
        for metric in ("files", "ranges", "visible"):
            summary[f"{metric}_{page}"] = sum(len(r["pages"][page]["hits"][metric]) for r in rows)
    summary["inspection_visible"] = sum(len(r["inspection_hits"]) for r in rows)
    seconds = [r["pages"]["5"]["seconds"] for r in rows]
    summary["p95_seconds"] = sorted(seconds)[math.ceil(.95 * len(seconds)) - 1]
    return summary


def compare(baseline, candidate, expected_ids):
    """Correctness acceptance, not a claim of statistically proven usefulness."""
    if (not baseline or {r["id"] for r in baseline} != set(expected_ids)
            or {r["id"] for r in baseline} != {r["id"] for r in candidate}):
        raise ValueError("Require complete paired frozen questions")
    if len({r["id"] for r in baseline}) != len(baseline) or len(candidate) != len(baseline):
        raise ValueError("Duplicate questions")
    b, c = summarize(baseline), summarize(candidate)
    losses = []
    by_id = {r["id"]: r for r in candidate}
    for old in baseline:
        new = by_id[old["id"]]
        if old["query"] != new["query"] or old["evidence"] != new["evidence"]:
            raise ValueError("Judgments changed between arms")
        for page in ("5", "24", "scoped"):
            if old["pages"][page]["request"] != new["pages"][page]["request"]:
                raise ValueError("Consumer request changed between arms")
            for metric in ("files", "visible"):
                missing = set(old["pages"][page]["hits"][metric]) - set(new["pages"][page]["hits"][metric])
                if missing:
                    losses.append({"id": old["id"], "page": page, "metric": metric, "labels": sorted(missing)})
    checks = {"file_totals_no_loss": all(c[f"files_{p}"] >= b[f"files_{p}"] for p in ("5", "24", "scoped")),
              "visible_totals_no_loss": all(c[f"visible_{p}"] >= b[f"visible_{p}"] for p in ("5", "24", "scoped")),
              "scoped_no_individual_loss": not any(x["page"] == "scoped" for x in losses),
              "inspection_no_net_loss": c["inspection_visible"] >= b["inspection_visible"],
              "latency": c["p95_seconds"] <= max(.1, b["p95_seconds"] * 1.5)}
    return {"passed": all(checks.values()), "checks": checks, "baseline": b, "candidate": c,
            "individual_losses": losses}


async def run(args):
    if args.output.exists():
        raise ValueError("Refusing to overwrite observations")
    raw = args.questions.read_bytes()
    design = json.loads(raw)
    group = next(g for g in design["repositories"] if g["pack"] == args.pack)
    identity = fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"])
    engine = engine_identity()
    for q in group["queries"]:
        for e in q["evidence"]:
            path = (args.source / e["file"]).resolve()
            if not path.is_relative_to(args.source.resolve()):
                raise ValueError("Label escapes source")
            content = path.read_bytes()
            lines = content.decode().splitlines()
            if hashlib.sha256(content).hexdigest() != e["source_sha256"] or e["quote"] not in lines[e["line"] - 1]:
                raise ValueError("Source judgment changed")
    calls = {"posted": 0, "refused": 0}
    stack = ExitStack()
    if args.max_rerank_calls is not None:
        from attocode_intel._internal.integrations.context.systemone_ranker import (
            SystemOneChoiceReranker,
        )

        post = SystemOneChoiceReranker._post

        def counted_post(ranker, body, headers):
            # Refuse before the request leaves the machine; the run then aborts.
            if calls["posted"] >= args.max_rerank_calls:
                calls["refused"] += 1
                raise RuntimeError("Rerank call limit reached")
            calls["posted"] += 1
            return post(ranker, body, headers)

        stack.enter_context(patch.object(SystemOneChoiceReranker, "_post", counted_post))

    embed = {"posted": 0, "refused": 0, "cost": 0.0, "models": []}
    if args.max_embed_calls is not None or args.embed_spend_limit is not None:
        from attocode_intel._internal.integrations.context.embeddings import (
            OpenRouterEmbeddingProvider,
        )

        embed_post = OpenRouterEmbeddingProvider._post
        embed_lock = threading.Lock()

        def counted_embed(provider, body):
            # Refuse before the request leaves the machine. The provider turns the
            # error into an empty vector, so check_calls() aborts the run.
            with embed_lock:
                if ((args.max_embed_calls is not None and embed["posted"] >= args.max_embed_calls)
                        or (args.embed_spend_limit is not None and embed["cost"] >= args.embed_spend_limit)):
                    embed["refused"] += 1
                    raise RuntimeError("Embedding call or spend limit reached")
                embed["posted"] += 1
            data = embed_post(provider, body)
            usage = data.get("usage") if isinstance(data, dict) else None
            cost = usage.get("cost") if isinstance(usage, dict) else None
            model = data.get("model") if isinstance(data, dict) else None
            with embed_lock:
                if isinstance(cost, int | float) and not isinstance(cost, bool):
                    embed["cost"] += cost
                if model not in embed["models"]:
                    embed["models"].append(model)
            return data

        stack.enter_context(patch.object(OpenRouterEmbeddingProvider, "_post", counted_embed))

    def check_calls():
        if calls["refused"]:
            raise RuntimeError(f"Rerank call limit {args.max_rerank_calls} reached")
        if embed["refused"]:
            raise RuntimeError(f"Embedding limit reached: {embed}")

    gateway = OperationGateway(str(args.source), profile="daily", watch=False)
    rows = []
    preflight = []
    embed_preflight = []
    embed_index = None
    try:
        started = time.perf_counter()
        # Public warmup first, then wait on the gateway's owned worker.
        decode(await gateway.execute_mcp("semantic_search", {"query": "warmup", "top_k": 24}))
        key = next(iter(gateway._stores))
        mgr = gateway._stores[key]["service"]._get_semantic_search()
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(gateway._workers[key],
                                          lambda: mgr.wait_for_body_index(timeout=args.warmup_timeout)):
            raise TimeoutError("Index warmup incomplete")
        setup_seconds = time.perf_counter() - started
        check_calls()
        if os.environ.get("ATTOCODE_INTEL_EMBEDDING"):
            # The explicit index is the spend consent; search alone never embeds the pack.
            started = time.perf_counter()
            chunks = await loop.run_in_executor(gateway._workers[key], mgr.index)
            provider = mgr._provider
            embed_index = {"chunks": chunks, "seconds": time.perf_counter() - started,
                           "stored": mgr._store.count() if mgr._store is not None else 0,
                           **{k: getattr(provider, k, None) for k in ("name", "requests", "tokens", "cost", "abort")}}
            check_calls()
            if not chunks or embed_index["abort"]:
                raise RuntimeError(f"Hosted embedding index failed: {embed_index}")
        if args.require_embed:
            # A non-frozen query proves the dense list before any frozen question runs.
            for _ in range(3):
                mgr._dense_last = {}
                await observe(gateway, "load settings from a configuration file", top_k=5, budget=design["budget"])
                embed_preflight.append(dict(mgr._dense_last))
                check_calls()
                if mgr._dense_last.get("status") == "ok" and mgr._dense_last.get("files"):
                    break
            else:
                diag = await loop.run_in_executor(gateway._workers[key], embed_diagnostic, mgr)
                check_calls()
                raise RuntimeError(f"Hosted embedding preflight failed: {embed_preflight} {diag}")
        if args.require_rerank:
            # A non-frozen query proves the hosted path before any frozen question runs.
            for _ in range(3):
                result = await observe(gateway, "load settings from a configuration file", top_k=5,
                                       budget=design["budget"])
                preflight.append(result["ranking_diagnostic"])
                check_calls()
                if any(r.get("method") == "systemone_choice" for r in result["ranking_diagnostic"]):
                    break
            else:
                raise RuntimeError(f"Hosted rerank preflight failed: {preflight}")
        for q in group["queries"]:
            pages = {}
            for page in ("5", "24", "scoped"):
                samples = []
                for _ in range(3):
                    # Empty after the call means this request did not run the dense list.
                    mgr._dense_last = {}
                    result = await observe(gateway, q["query"], top_k=5 if page == "scoped" else int(page),
                                           budget=design["budget"], mode=q.get("mode", "auto"),
                                           file_filter=q["evidence"][0]["file"] if page == "scoped" else "",
                                           capture_generation=args.capture_generation)
                    result["dense"] = dict(mgr._dense_last)
                    check_calls()
                    result["hits"] = evidence_hits(result["response"]["data"]["results"], q["evidence"])
                    if (samples and not args.samples_may_differ
                            and samples[0]["response"]["data"]["results"] != result["response"]["data"]["results"]):
                        raise RuntimeError("Unstable warmed delivery")
                    samples.append(result)
                pages[page] = result
                result["seconds"] = statistics.median(s["seconds"] for s in samples)
                result["samples_seconds"] = [s["seconds"] for s in samples]
                if args.samples_may_differ:
                    result["samples"] = [{"seconds": s["seconds"], "hits": s["hits"], "dense": s["dense"],
                                          "ranking_diagnostic": s["ranking_diagnostic"],
                                          "results": s["response"]["data"]["results"]} for s in samples]
                    result["hits"] = worst_of(samples)
            inspection = await inspect_first_named(gateway, pages["5"]["response"]["data"]["results"],
                                                   q["query"], design["budget"])
            rows.append({**q, "pack": args.pack, "pages": pages, "inspection": inspection,
                         "inspection_hits": inspect_hits(inspection, q["evidence"])})
        check_calls()
    finally:
        await gateway.close()
        stack.close()
    if identity != fingerprint([REPO / "packages/code-intel/src", REPO / "eval/quality"]) or engine != engine_identity():
        raise RuntimeError("Evaluator source changed")
    args.output.write_text(json.dumps({"arm": args.arm, "pack": args.pack, "commit": group["commit"],
                                      "setup_seconds": setup_seconds, "queries": rows,
                                      "rerank_calls": calls, "preflight": preflight,
                                      "embed_calls": embed, "embed_index": embed_index,
                                      "embed_preflight": embed_preflight,
                                      "samples_may_differ": args.samples_may_differ,
                                      "questions_sha256": hashlib.sha256(raw).hexdigest(),
                                      "operator_sha256": identity, "engine_sha256": engine}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("questions", "source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--capture-generation", action="store_true",
                        help="Record pre-penalty keyword/body/file candidates without changing delivery")
    parser.add_argument("--samples-may-differ", action="store_true",
                        help="Keep differing samples and score labels every sample delivered")
    parser.add_argument("--max-rerank-calls", type=int,
                        help="Abort before the request that would exceed this many hosted rerank calls")
    parser.add_argument("--require-rerank", action="store_true",
                        help="Abort unless a non-frozen query reaches the hosted ranker first")
    parser.add_argument("--max-embed-calls", type=int,
                        help="Abort before the request that would exceed this many hosted embedding calls")
    parser.add_argument("--embed-spend-limit", type=float,
                        help="Abort before a hosted embedding request once reported cost reaches this (USD)")
    parser.add_argument("--require-embed", action="store_true",
                        help="Abort unless a non-frozen query runs the hosted dense list first")
    parser.add_argument("--warmup-timeout", type=float, default=90)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
