"""Frozen actual-page comparison for one test-result file-diversity candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from attocode_intel import query_ranking
from attocode_intel._internal.integrations.context.semantic_search import (
    SemanticSearchManager,
    _expand_query,
)
from attocode_intel.focused_evidence import terms

from eval.quality.runner import REPO, fingerprint

_BASE_DIVERSITY = query_ranking._default_file_diversity


def candidate_diversity(query, candidates, top_k, file_filter):
    """Use distinct files for short explicit test searches; preserve all other cases."""
    import re

    eligible = (not file_filter and re.search(r"\btests?\b", query, re.I)
                and len(terms(query)) <= 20 and len(query_ranking.query_concepts(query)) >= 2)
    if not eligible:
        return _BASE_DIVERSITY(query, candidates, top_k, file_filter)
    selected, repeated, seen = [], [], set()
    for row in candidates:
        if row.file_path in seen:
            repeated.append(row)
        else:
            selected.append(row)
            seen.add(row.file_path)
    return (selected + repeated)[:top_k]


def snapshot(hits):
    return [{"file": h.file_path, "name": h.name, "kind": h.chunk_type,
             "score": h.score, "start_line": h.start_line, "end_line": h.end_line,
             "excerpt": h.text[:500]} for h in hits]


def observed_anchors(results, evidence):
    """Anchors inside delivered chunk ranges, not proof the UI displayed that line."""
    return [i for i, e in enumerate(evidence) if any(
        r["file"] == e["file"] and 0 < r["start_line"] <= e["line"] <= r["end_line"]
        for r in results)]


def summarize(rows, arm):
    answer = {"questions": len(rows)}
    for k in (5, 24):
        pairs = [len(set(r["labels"]) & {h["file"] for h in r["arms"][arm][str(k)]["results"]}) for r in rows]
        answer.update({f"pairs{k}": sum(pairs), f"any{k}": sum(n > 0 for n in pairs),
                       f"all{k}": sum(n == len(r["labels"]) for n, r in zip(pairs, rows, strict=True)),
                       f"anchor_ranges{k}": sum(len(r["arms"][arm][str(k)]["anchor_ranges"]) for r in rows)})
    latencies = [r["arms"][arm]["5"]["seconds"] for r in rows]
    answer["p95_seconds"] = sorted(latencies)[math.ceil(.95 * len(latencies)) - 1]
    return answer


def decide(rows, expected_ids):
    if (len(rows) != 12 or len({r["id"] for r in rows}) != 12
            or {r["id"] for r in rows} != set(expected_ids)
            or any(len(r["labels"]) != 2 or set(r["arms"]) != {"baseline", "candidate"} for r in rows)):
        raise ValueError("Requires the twelve frozen paired questions with two labels each")
    before, after = (summarize(rows, a) for a in ("baseline", "candidate"))
    improved, losses, anchor_losses = [], [], []
    generation, controls = True, True
    for row in rows:
        b, c = row["arms"]["baseline"], row["arms"]["candidate"]
        labels = set(row["labels"])
        b5, c5 = ({h["file"] for h in x["5"]["results"]} & labels for x in (b, c))
        if len(c5) > len(b5):
            improved.append(row)
        for k in ("5", "24"):
            if not ({h["file"] for h in b[k]["results"]} & labels) <= {h["file"] for h in c[k]["results"]}:
                losses.append(row["id"] + ":" + k)
            if not set(b[k]["anchor_ranges"]) <= set(c[k]["anchor_ranges"]):
                anchor_losses.append(row["id"] + ":" + k)
            generation &= b[k]["stages"] == c[k]["stages"]
            if row["category"] != "tests":
                controls &= b[k]["results"] == c[k]["results"]
        controls &= b["scoped"]["results"] == c["scoped"]["results"]
    checks = {"net_pairs5_at_least_two": after["pairs5"] - before["pairs5"] >= 2,
              "two_improved_queries": len(improved) >= 2,
              "two_improved_repositories": len({r["pack"] for r in improved}) >= 2,
              "no_individual_label_losses": not losses,
              "no_delivered_anchor_range_losses": not anchor_losses,
              "generation_identical": generation, "controls_identical": controls,
              "latency": after["p95_seconds"] <= max(before["p95_seconds"] * 1.5, .05)}
    return {"passed": all(checks.values()), "checks": checks, "baseline": before, "candidate": after,
            "improved": [r["id"] for r in improved], "label_losses": losses,
            "anchor_range_losses": anchor_losses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--pack', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite observations')
    os.environ['ATTOCODE_INTEL_BROAD_RERANK'] = '0'
    os.environ['ATTOCODE_LOCAL_ONLY'] = '1'
    raw = args.questions.read_bytes()
    design = json.loads(raw)
    if args.baseline_only and design['split'] != 'development':
        parser.error('Only development may be diagnosed before candidate freeze')
    group = next(g for g in design['repositories'] if g['pack'] == args.pack)
    identity = fingerprint([REPO / 'packages/code-intel/src', REPO / 'eval/quality'])
    mgr = SemanticSearchManager(str(args.source))
    rows = []
    try:
        started = time.perf_counter()
        mgr.search('warmup', top_k=24)
        if not mgr.wait_for_body_index(timeout=90):
            raise TimeoutError('Index warmup incomplete')
        setup_seconds = time.perf_counter() - started
        for number, q in enumerate(group['queries']):
            for e in q['evidence']:
                path = (args.source / e['file']).resolve()
                if not path.is_relative_to(args.source.resolve()):
                    raise ValueError('Label escapes source')
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != e['source_sha256'] or e['quote'] not in content.decode():
                    raise ValueError('Source judgment changed')
            arms = {a: {} for a in (['baseline'] if args.baseline_only else ['baseline', 'candidate'])}
            for size in (5, 24, 'scoped'):
                k, scope = (5, q['evidence'][0]['file']) if size == 'scoped' else (size, '')
                samples = {a: [] for a in arms}
                for repeat in range(3):
                    order = list(arms)
                    if (repeat + number) % 2:
                        order.reverse()
                    for arm in order:
                        trace = {}
                        fn = _BASE_DIVERSITY if arm == 'baseline' else candidate_diversity
                        started = time.perf_counter()
                        with patch.object(query_ranking, '_default_file_diversity', fn):
                            hits = mgr.search_candidates(_expand_query(q['query']), top_k=k,
                                                         file_filter=scope, trace=trace)
                        samples[arm].append(time.perf_counter() - started)
                        result = snapshot(hits)
                        previous = arms[arm].get(str(size))
                        if previous and previous['results'] != result:
                            raise RuntimeError('Unstable warmed results')
                        arms[arm][str(size)] = {'results': result, 'stages': trace,
                                               'anchor_ranges': observed_anchors(result, q['evidence'])}
                for arm in arms:
                    arms[arm][str(size)].update(seconds=statistics.median(samples[arm]), samples_seconds=samples[arm])
            rows.append({'id': q['id'], 'pack': args.pack, 'category': q['category'],
                         'query': q['query'], 'labels': [e['file'] for e in q['evidence']], 'arms': arms})
        index = mgr.candidate_diagnostics()
    finally:
        mgr.close()
    if identity != fingerprint([REPO / 'packages/code-intel/src', REPO / 'eval/quality']):
        raise RuntimeError('Source changed during comparison')
    args.output.write_text(json.dumps({'pack': args.pack, 'commit': group['commit'], 'queries': rows,
                                      'setup_seconds': setup_seconds, 'index': index,
                                      'questions_sha256': hashlib.sha256(raw).hexdigest(),
                                      'source_sha256': identity}, indent=2) + '\n')


if __name__ == '__main__':
    main()
