"""One frozen synthetic qualification against the installed release; Actions only."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

from attocode_intel.gateway import OperationGateway
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager

PROTOCOL = json.loads('{\n  "version": "body-row-cap-v1",\n  "product_version": "0.1.39",\n  "released_commit": "ed74f9a6f2190186e2e59a4435860ed7a4a9fd7d",\n  "wheel_sha256": "0deaaa567853cbc48964ea69dc79b4996a60e37aa1c245b68580861f1cb58f53",\n  "query": "sapphire quartz",\n  "fixtures": {\n    "saturated": {\n      "a.py_execute_repeats": 600,\n      "b.py_execute_repeats": 1\n    },\n    "unsaturated": {\n      "a.py_execute_repeats": 16,\n      "b.py_execute_repeats": 1\n    },\n    "owners": {\n      "a.py_execute_repeats": 16,\n      "a.py_other_repeats": 1\n    }\n  },\n  "primary_top_k": 10,\n  "max_tokens": 2000,\n  "mode": "keyword",\n  "profile": "daily",\n  "watch": false,\n  "enumeration_limit": 1200,\n  "operator_timeout_seconds": 180,\n  "test_files": {\n    "packages/code-intel/tests/test_chunk_identity.py": "eda17f496c624c101b3d31cc76f091ca534541a7fdde1b62b09f333e19985d80",\n    "packages/code-intel/tests/test_query_ranking.py": "5262a1a80db2f23d2b3bdd54d6c32a110dc03adadaea8619f3bccf396e11b432",\n    "packages/code-intel/tests/test_search_budget_repair.py": "d335b6fbe4fab6521d0c568431ec1f3b703218ab7e0b44abaa2a7d08ff5bd30e",\n    "packages/code-intel/tests/unit/integrations/context/test_semantic_search.py": "ae864eeb84509828b3b5c3a3fb5be0cd27c7cf023caf47998cf4e06435c1e45d"\n  },\n  "maintained_test_function_identities": [\n    "test_chunk_identity::test_anonymous_and_macro_windows_keep_distinct_source_ranges",\n    "test_chunk_identity::test_duplicate_retrieval_rows_do_not_multiply_rrf_evidence",\n    "test_chunk_identity::test_extra_windows_preserve_navigation_to_other_named_owners",\n    "test_chunk_identity::test_java_overloads_fuse_individually_and_reopen_without_losing_metadata",\n    "test_chunk_identity::test_long_named_method_keeps_windows_and_keyword_boost_once",\n    "test_chunk_identity::test_span_cache_after_changes_matches_current_source",\n    "test_chunk_identity::test_v2_keyword_cache_is_invalidated_and_newer_cache_is_not_modified",\n    "test_chunk_identity::test_v3_keyword_cache_is_rebuilt_with_python_docstrings",\n    "test_query_ranking::test_broad_ranker_is_off_by_default_but_file_page_is_diverse",\n    "test_query_ranking::test_compact_budget_keeps_each_delivered_match_explanation_complete",\n    "test_query_ranking::test_complete_match_stays_with_best_implementation_component",\n    "test_query_ranking::test_concept_evidence_promotes_full_match_and_diversifies_files",\n    "test_query_ranking::test_deeper_page_keeps_available_files_before_repeated_chunks",\n    "test_query_ranking::test_equal_lexical_scores_have_stable_file_order_across_cold_builds",\n    "test_query_ranking::test_explicit_exclusion_is_not_reversed_by_full_match_bonus",\n    "test_query_ranking::test_file_diversity_retains_count_order_and_all_chunks_when_room",\n    "test_query_ranking::test_long_queries_and_archive_matches_keep_previous_order",\n    "test_query_ranking::test_next_search_page_reuses_pool_and_handles_budget_omissions",\n    "test_query_ranking::test_prose_words_are_not_search_terms",\n    "test_query_ranking::test_real_source_index_keeps_multiple_interpretations_visible",\n    "test_query_ranking::test_scoped_query_does_not_claim_cross_component_ambiguity",\n    "test_query_ranking::test_structured_search_exposes_match_evidence_and_ambiguity",\n    "test_search_budget_repair::test_budget_does_not_mutate_callers_rows",\n    "test_search_budget_repair::test_budget_fills_prefix_instead_of_halving_with_spare_room",\n    "test_search_budget_repair::test_complete_recovery_reports_only_remaining_truncation",\n    "test_search_budget_repair::test_deeper_hint_survives_complete_current_pool_without_changing_rows",\n    "test_search_budget_repair::test_existing_oversized_hint_cannot_make_usable_page_fail",\n    "test_search_budget_repair::test_gateway_keeps_candidates_until_final_fit_and_offers_progress",\n    "test_search_budget_repair::test_new_follow_up_never_crowds_out_previously_delivered_evidence",\n    "test_search_budget_repair::test_no_deeper_probe_for_unsaturated_pool_or_automatic_ceiling",\n    "test_search_budget_repair::test_noncompact_search_retains_its_existing_budget_followup",\n    "test_search_budget_repair::test_remote_search_follow_up_keeps_resolved_revision",\n    "test_search_budget_repair::test_saturated_search_offers_bounded_deeper_followup",\n    "test_search_budget_repair::test_search_delivery_invariants_across_budget_boundaries",\n    "test_search_budget_repair::test_truncation_provenance_itself_is_included_in_budget",\n    "test_search_budget_repair::test_unfittable_new_hint_keeps_a_usable_response",\n    "test_semantic_search.TestSourceBodyCandidates::test_body_filter_applies_before_rank_limit",\n    "test_semantic_search.TestSourceBodyCandidates::test_body_hit_format_includes_exact_window",\n    "test_semantic_search.TestSourceBodyCandidates::test_cold_request_reports_warming_without_blocking_or_loading_model",\n    "test_semantic_search.TestSourceBodyCandidates::test_direct_edit_does_not_return_stale_body_hit",\n    "test_semantic_search.TestSourceBodyCandidates::test_exclusion_penalty_applies_before_lexical_limit",\n    "test_semantic_search.TestSourceBodyCandidates::test_fallback_when_fts_unavailable",\n    "test_semantic_search.TestSourceBodyCandidates::test_file_fusion_is_equal_weight_rrf_of_file_orders",\n    "test_semantic_search.TestSourceBodyCandidates::test_finds_body_only_implementation_with_line_span",\n    "test_semantic_search.TestSourceBodyCandidates::test_invalidation_updates_body_and_removes_deleted_file",\n    "test_semantic_search.TestSourceBodyCandidates::test_lexical_fusion_fields_change_candidates",\n    "test_semantic_search.TestSourceBodyCandidates::test_long_query_keeps_its_rarest_body_terms",\n    "test_semantic_search.TestSourceBodyCandidates::test_plural_query_word_matches_the_same_plural_in_code",\n    "test_semantic_search.TestSourceBodyCandidates::test_query_escaping_and_soft_exclusion",\n    "test_semantic_search.TestSourceBodyCandidates::test_ready_lexical_search_still_does_not_load_model",\n    "test_semantic_search.TestSourceBodyCandidates::test_source_body_index_does_not_follow_outside_symlink",\n    "test_semantic_search.TestSourceBodyCandidates::test_source_cache_is_private",\n    "test_semantic_search.TestSourceBodyCandidates::test_trace_records_the_file_order_of_each_stage",\n    "test_semantic_search.TestSourceBodyCandidates::test_warmup_discovers_files_once",\n    "test_semantic_search.TestSourceBodyCandidates::test_whole_file_bm25_sees_matches_spread_over_a_file",\n    "test_semantic_search.TestSourceBodyCandidates::test_whole_file_search_skips_docs"\n  ],\n  "controls": [\n    "exact_scope_before_limit",\n    "unsaturated_two_files",\n    "owner_priority_and_distinct_windows",\n    "traced_untraced_public_payload_equivalence",\n    "raw_body_prefix_and_admitted_list_equivalence",\n    "installed_wheel_source_identity",\n    "owned_cleanup"\n  ],\n  "outcomes": {\n    "confirmed": "saturated raw576 rows all a.py; indexed target beyond576/in bounded enumeration; only8a.py admitted and primary target absent; exactscope+unsaturatedtargetvisible; all controls pass",\n    "not_reproduced": "complete identity/control-valid observation does not meet primary causal chain",\n    "incomplete": "setup/control/source/provenance/bounds/cleanup failure; never product RED"\n  },\n  "limits": "Synthetic mechanism qualification only; no real question or two-repository eligibility or general quality/latency claim. No production change or new release."\n}\n')
QUERY = "sapphire quartz"
UNIT = 'def execute(value):\n    return "sapphire quartz"\n\n'
OTHER = 'def other(value):\n    return "sapphire quartz"\n\n'
sha = lambda b: hashlib.sha256(b).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def snapshot(root):
    return {"head": git(root, "rev-parse", "HEAD"), "files": {
        p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size,
                 "mtime_ns": p.stat().st_mtime_ns}
        for p in sorted(root.glob("*.py"))}}


def prepare(root, label, output):
    root.mkdir()
    repeats = 600 if label == "saturated" else 16
    files = {"a.py": UNIT * repeats}
    if label == "owners":
        files["a.py"] += OTHER
    else:
        files["b.py"] = UNIT
    source_out = output / "fixtures" / label
    source_out.mkdir(parents=True)
    for name, source in files.items():
        (root / name).write_text(source)
        (source_out / name).write_text(source)
    (root / ".gitignore").write_text(".attocode/\n")
    git(root, "init", "-b", "fixture")
    git(root, "config", "user.name", "Synthetic row-cap fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-m", "frozen fixture")


def decode(response, record, response_key="response", decoded_key="decoded"):
    raw = response.model_dump(mode="json", exclude_none=True)
    record[response_key] = raw
    assert not response.isError, response
    payload = json.loads(response.content[0].text)
    record[decoded_key] = payload
    assert "error" not in payload.get("data", {}), payload
    return raw, payload


def result_rows(rows):
    return [r if isinstance(r, str) else asdict(r) for r in rows]


class CursorCapture:
    def __init__(self, cursor, event):
        self.cursor, self.event = cursor, event

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.event["rows"] = [list(row) for row in rows]
        return rows

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class ConnectionCapture:
    def __init__(self, connection, events):
        self.connection, self.events = connection, events

    def execute(self, sql, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        if sql.startswith("SELECT body_fts.file_path, chunk_type, name, start_line, end_line, "):
            event = {"sql": sql, "parameters": list(parameters)}
            self.events.append(event)
            return CursorCapture(cursor, event)
        return cursor

    def __getattr__(self, name):
        return getattr(self.connection, name)


async def observe(gateway, manager, request, observation):
    stages, raw_sql = [], []
    observation.update(request=request, stages=stages, raw_sql_events=raw_sql)
    open_db = SemanticSearchManager._open_body_db

    def opened(instance):
        connection = open_db(instance)
        return ConnectionCapture(connection, raw_sql) if connection is not None else None

    with ExitStack() as stack:
        stack.enter_context(patch.object(SemanticSearchManager, "_open_body_db", opened))
        for method, label in (("_keyword_search", "keyword"), ("_body_search", "body"), ("_file_search", "file")):
            original = getattr(SemanticSearchManager, method)

            def captured(instance, *args, _original=original, _label=label, **kwargs):
                rows = _original(instance, *args, **kwargs)
                stages.append({"stage": _label, "arguments": list(args), "keywords": kwargs,
                               "results": result_rows(rows)})
                return rows

            stack.enter_context(patch.object(SemanticSearchManager, method, captured))
        raw, public = decode(await gateway.execute_mcp("semantic_search", request), observation)
    assert public["data"]["ranking"]["index"]["status"] == "ready", public
    assert public["metadata"]["source"] == "local"
    assert len(raw_sql) == 1 and len(stages) == 3, (raw_sql, stages)
    # A second public control uses the original methods, without wrappers.
    observation["raw_sql"] = raw_sql[0]
    plain_raw, plain = decode(await gateway.execute_mcp("semantic_search", request), observation,
                              "untraced_response", "untraced_decoded")
    assert plain["data"] == public["data"], "capture changed the public payload"
    loop = asyncio.get_running_loop()
    key = next(iter(gateway._workers))

    def diagnostic():
        sql = raw_sql[0]
        result = observation.setdefault("enumeration", {})
        conn = open_db(manager)
        try:
            assert conn is not None
            parameters = list(sql["parameters"])
            parameters[-1] = 1200
            result.update(sql=sql["sql"], parameters=parameters)
            rows = [list(row) for row in conn.execute(sql["sql"], parameters).fetchall()]
            result["rows"] = rows
            # A count on the same MATCH and scope proves the bounded enumeration is complete.
            where = "terms MATCH ?"
            count_parameters = [sql["parameters"][0]]
            if request["file_filter"]:
                where += " AND body_fts.file_path GLOB ?"
                count_parameters.append(request["file_filter"].replace("[!", "[^"))
            count = conn.execute("SELECT count(*) FROM body_fts WHERE " + where, count_parameters).fetchone()[0]
            indexed = [list(r) for r in conn.execute("SELECT file_path,mtime_ns,size FROM body_files ORDER BY file_path")]
            result.update(match_count=count, indexed_files=indexed)
        finally:
            if conn is not None:
                conn.close()
        assert len(rows) == count < 1200
        assert rows[:len(sql["rows"])] == sql["rows"]
        body = next(s for s in stages if s["stage"] == "body")
        direct = result_rows(manager._body_search(*body["arguments"], **body["keywords"]))
        result["direct_body"] = direct
        assert direct == body["results"], "capture changed admitted body results"
        result["direct_producers"] = {}
        for label, method in (("keyword", "_keyword_search"), ("file", "_file_search")):
            original = next(s for s in stages if s["stage"] == label)
            direct = result_rows(getattr(manager, method)(*original["arguments"], **original["keywords"]))
            result["direct_producers"][label] = direct
            assert direct == original["results"], "capture changed " + label + " results"
        return result

    full = await loop.run_in_executor(gateway._workers[key], diagnostic)
    observation.update(enumeration=full, passivity={"public_data_equal": True, "all_producer_results_equal": True})
    return observation


async def run_case(directory, label, record, output):
    root = directory / label
    prepare(root, label, output)
    record.update(label=label, workspace=str(root), source_before=snapshot(root), observations=[])
    gateway = OperationGateway(str(root), profile="daily", watch=False)
    try:
        warm_request = {"query": "controlwarmup", "top_k": 24, "mode": "keyword", "max_tokens": 2000}
        warmup = record.setdefault("warmup", {"request": warm_request})
        warm_raw, _ = decode(await gateway.execute_mcp("semantic_search", warm_request), warmup)
        key = next(iter(gateway._stores))
        manager = gateway._stores[key]["service"]._get_semantic_search()
        loop = asyncio.get_running_loop()
        ready = await loop.run_in_executor(gateway._workers[key], lambda: manager.wait_for_body_index(timeout=30))
        assert ready and manager._kw_index_built and manager._body_index_built
        assert manager.scoring_config.max_chunks_per_file == 8
        scopes = ["", "b.py"] if label == "saturated" else (["a.py"] if label == "owners" else [""])
        for scope in scopes:
            request = {"query": QUERY, "top_k": 10, "file_filter": scope, "max_tokens": 2000, "mode": "keyword"}
            observation = {"request": request}
            record["observations"].append(observation)
            await observe(gateway, manager, request, observation)
    finally:
        await gateway.close()
        record["gateway_closed"] = gateway._closed and not gateway._workers and not gateway._stores
        record["source_after"] = snapshot(root)
        assert record["source_before"] == record["source_after"] and record["gateway_closed"]


def paths(observation):
    return {h["file_path"] for h in observation["decoded"]["data"]["results"]}


def stage(observation, name):
    return next(s["results"] for s in observation["stages"] if s["stage"] == name)


def decide(report):
    assert not report["harness_errors"]
    by_label = {c["label"]: c for c in report["cases"]}
    primary, scoped = by_label["saturated"]["observations"]
    ordinary, = by_label["unsaturated"]["observations"]
    owners, = by_label["owners"]["observations"]
    for case in report["cases"]:
        assert case["gateway_closed"] and case["source_before"] == case["source_after"]
        for o in case["observations"]:
            assert o["passivity"] == {"public_data_equal": True, "all_producer_results_equal": True}
            assert not stage(o, "keyword") and not stage(o, "file"), "another producer rescues the fixture"
            hits = o["decoded"]["data"]["results"]
            assert hits and all(QUERY in h["snippet"] and not h["snippet_truncated"] for h in hits)
            assert not o["decoded"]["metadata"]["truncated"]
            assert o["decoded"]["metadata"]["workspace"] == case["workspace"]
            for hit in hits:
                source = (Path(case["workspace"]) / hit["file_path"]).read_text().splitlines()
                first, last = hit["snippet_start_line"], hit["snippet_end_line"]
                assert 1 <= first <= last <= len(source)
                assert hit["snippet"] == "\n".join(source[first - 1:last])
            body = stage(o, "body")
            assert len({(h["file_path"], h["start_line"], h["end_line"]) for h in body}) == len(body)
    assert paths(scoped) == {"b.py"} and len(stage(scoped, "body")) == 1
    assert paths(ordinary) == {"a.py", "b.py"} and len(stage(ordinary, "body")) == 9
    assert len(ordinary["raw_sql"]["rows"]) == ordinary["enumeration"]["match_count"] == 17
    assert paths(owners) == {"a.py"} and {h["name"] for h in stage(owners, "body")} == {"execute", "other"}
    assert {h["name"] for h in owners["decoded"]["data"]["results"]} == {"execute", "other"}
    assert len(stage(owners, "body")) == 8 and len(owners["raw_sql"]["rows"]) == 17
    for observation in (ordinary, owners):
        hits = observation["decoded"]["data"]["results"]
        assert hits[0]["score"] == round(1.15 / 21, 6), "duplicate windows multiplied the owner vote"
    raw, all_rows, admitted = primary["raw_sql"], primary["enumeration"]["rows"], stage(primary, "body")
    target_ordinals = [i for i, r in enumerate(all_rows, 1) if r[0] == "b.py"]
    assert len(all_rows) == 601 and len(target_ordinals) == 1, "fixture/index inventory incomplete"
    chain = {"raw_limit_576": raw["parameters"][-1] == 576,
             "raw_prefix_saturated_by_one_file": len(raw["rows"]) == 576 and {r[0] for r in raw["rows"]} == {"a.py"},
             "target_indexed_beyond_prefix": all(i > 576 for i in target_ordinals),
             "per_file_cap_leaves_eight": len(admitted) == 8 and {h["file_path"] for h in admitted} == {"a.py"},
             "target_absent_first_public_response": paths(primary) == {"a.py"},
             "public_pool_underfilled": primary["decoded"]["data"]["ranking"]["candidate_pool_count"] == 8}
    report.update(controls_passed=True, causal_chain=chain, target_sql_ordinals=target_ordinals,
                  exploration_hint_present="follow_up" in primary["decoded"]["data"],
                  verdict="confirmed" if all(chain.values()) else "not_reproduced")


async def main(output):
    output.mkdir(parents=True, exist_ok=True)
    assert version("attocode-code-intel") == "0.1.39" and sys.platform == "linux"
    report = {"protocol": PROTOCOL, "product_version": version("attocode-code-intel"),
              "product_head": git(Path.cwd(), "rev-parse", "HEAD^"), "diagnostic_head": git(Path.cwd(), "rev-parse", "HEAD"),
              "cases": [], "harness_errors": [], "verdict": "incomplete"}
    owned = None
    try:
        with tempfile.TemporaryDirectory(prefix="body-row-cap-", dir=os.environ["TMPDIR"]) as directory:
            owned = Path(directory)
            for label in ("saturated", "unsaturated", "owners"):
                record = {}
                report["cases"].append(record)
                try:
                    await run_case(owned, label, record, output)
                except Exception:
                    report["harness_errors"].append({"case": label, "traceback": traceback.format_exc()})
            if not report["harness_errors"]:
                decide(report)
    except Exception:
        report["harness_errors"].append({"phase": "decision", "traceback": traceback.format_exc()})
        report["verdict"] = "incomplete"
    finally:
        report["owned_fixture_removed"] = owned is not None and not owned.exists()
        report["tracked_source_unchanged"] = not git(Path.cwd(), "diff", "HEAD", "--")
        if not report["owned_fixture_removed"] or not report["tracked_source_unchanged"]:
            report["verdict"] = "incomplete"
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("verdict", "harness_errors", "owned_fixture_removed", "tracked_source_unchanged")}), flush=True)
    return 0 if report["verdict"] != "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(asyncio.wait_for(main(Path(sys.argv[1])), timeout=180)))
