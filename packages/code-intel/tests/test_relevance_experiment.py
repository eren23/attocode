"""Readiness, raw evidence, and quality gates for one frozen ranking study."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from eval.quality.experiment_evidence import Journal, encode
from eval.quality.fixture_identity import source_manifest
from eval.quality.readiness import coverage_ready, wait_ready
from eval.quality.relevance_experiment import (
    admit_arm,
    control_data,
    decide,
    page_identity,
    requests,
)


@pytest.mark.parametrize(
    "change", ["phase", "parsed", "references", "truncated", "rounded", "bool", "zero"]
)
def test_readiness_requires_exact_completed_counts(change):
    c = {
        "phase": "ready",
        "total_files": 1001,
        "parsed_files": 1001,
        "reference_indexed_files": 1001,
        "discovery_truncated": False,
    }
    assert coverage_ready(c)
    if change == "phase":
        c["phase"] = "hydrating"
    if change == "parsed":
        c["parsed_files"] = 1000
    if change == "references":
        c["reference_indexed_files"] = 1000
    if change == "truncated":
        c["discovery_truncated"] = True
    if change == "rounded":
        c.update(parsed_files=1000, parse_coverage=1.0)
    if change == "bool":
        c["reference_indexed_files"] = True
    if change == "zero":
        c["total_files"] = 0
    assert not coverage_ready(c)


@pytest.mark.asyncio
async def test_initialization_and_every_readiness_response_are_retained_before_inspection(tmp_path):
    journal = Journal(tmp_path / "journal", 8192)
    calls = []

    class Gateway:
        async def execute(self, name, args):
            calls.append(name)
            data = {
                "capabilities": {
                    "coverage": {
                        "phase": "ready",
                        "total_files": 1,
                        "parsed_files": 1,
                        "reference_indexed_files": 1,
                        "discovery_truncated": False,
                    }
                }
            }
            return SimpleNamespace(
                isError=False,
                structuredContent=data,
                model_dump=lambda **kw: {"content": [], "structuredContent": data},
            )

    result = await wait_ready(Gateway(), journal)
    assert calls == ["search_symbols", "capabilities"] and result["polls"] == 1
    events = [json.loads(line) for line in (journal.root / "events.jsonl").read_text().splitlines()]
    assert [e["request"]["event"] for e in events] == ["readiness_initialize", "readiness_poll"]
    assert all((journal.root / e["response"]["path"]).is_file() for e in events)


def grid():
    packs = [
        {
            "id": p,
            "questions": [
                {
                    "id": p + "q",
                    "kind": "behavior",
                    "query": "Where alpha beta?",
                    "evidence": [{"file": "a.py", "line": 1, "quote": "alpha"}],
                }
            ],
        }
        for p in ("one", "two")
    ]
    design = {
        "packs": packs,
        "stage": "validation",
        "rounds": [["baseline", "candidate"], ["candidate", "baseline"]],
        "requests": {
            "depths": [5, 24],
            "budgets": [2000, 8000],
            "scoped_depth": 5,
            "scoped_budget": 2000,
        },
    }
    reports = []
    for pack in packs:
        report = {"pack": pack["id"], "status": "complete", "pages": []}
        for n, arms in enumerate(design["rounds"]):
            for arm in arms:
                q = pack["questions"][0]
                for d, b, scope in requests(q, design):
                    gains = arm == "candidate" and d == 5 and not scope
                    report["pages"].append(
                        {
                            "round": n,
                            "arm": arm,
                            "question": q["id"],
                            "kind": q["kind"],
                            "arguments": {
                                "query": q["query"],
                                "top_k": d,
                                "max_tokens": b,
                                "file_filter": scope,
                            },
                            "milliseconds": 1,
                            "judgment": {"files": ["a.py"] if gains else [], "visible": []},
                            "data_sha256": "same",
                            "control_sha256": "same",
                        }
                    )
        reports.append(report)
    return reports, design


def test_gains_count_questions_and_repeat_in_every_round_not_settings():
    reports, design = grid()
    assert decide(reports, design)["decision"] == "retain"
    only = [reports[0]]
    design["packs"] = design["packs"][:1]
    assert decide(only, design)["decision"] == "reject"


@pytest.mark.parametrize(
    "damage", ["file_loss", "excerpt_loss", "control", "scope", "latency", "second_round", "order"]
)
def test_quality_failures_cannot_be_hidden_by_aggregate_gains(damage):
    reports, design = grid()
    rows = reports[0]["pages"]
    if damage in ("file_loss", "excerpt_loss"):
        row = next(r for r in rows if r["arm"] == "baseline" and r["arguments"]["top_k"] == 24)
        row["judgment"]["files" if damage == "file_loss" else "visible"] = (
            ["lost.py"] if damage == "file_loss" else [1]
        )
    elif damage == "control":
        for p in design["packs"]:
            p["questions"][0]["kind"] = "exact"
        for report in reports:
            for row in report["pages"]:
                row["kind"] = "exact"
                if row["arm"] == "candidate":
                    row["control_sha256"] = "changed"
    elif damage == "scope":
        next(r for r in rows if r["arm"] == "candidate" and r["arguments"]["file_filter"])[
            "control_sha256"
        ] = "changed"
    elif damage == "latency":
        for report in reports:
            for row in report["pages"]:
                if row["arm"] == "candidate":
                    row["milliseconds"] = 101
    elif damage == "second_round":
        for report in reports:
            for row in report["pages"]:
                if row["round"] == 1:
                    row["judgment"] = {"files": [], "visible": []}
    else:
        rows[0], rows[1] = rows[1], rows[0]
        with pytest.raises(ValueError):
            decide(reports, design)
        return
    assert decide(reports, design)["decision"] == "reject"


def capture(tmp_path):
    workspace, evidence, engine = tmp_path / "work", tmp_path / "evidence", tmp_path / "engine"
    workspace.mkdir()
    engine.mkdir()
    (workspace / "a.py").write_bytes(b"alpha\n")
    (engine / "__init__.py").write_bytes(b"")
    (engine / "query_ranking.py").write_bytes(b"")
    journal = Journal(evidence / "journal", 128 * 1024)
    source_sha = hashlib.sha256(b"alpha\n").hexdigest()
    spec = {
        "id": "one",
        "source_sha256": {"a.py": source_sha},
        "questions": [
            {
                "id": "q",
                "kind": "behavior",
                "query": "Where alpha beta?",
                "evidence": [
                    {"file": "a.py", "line": 1, "quote": "alpha", "source_sha256": source_sha}
                ],
            }
        ],
    }
    design = {
        "rounds": [["baseline", "candidate"]],
        "requests": {"depths": [5], "budgets": [2000], "scoped_depth": 5, "scoped_budget": 2000},
    }
    origin = {"attocode_intel": "__init__.py", "attocode_intel.query_ranking": "query_ranking.py"}
    journal.response({"event": "origin_start"}, origin)
    fixture = journal.response({"event": "fixture_before"}, source_manifest(workspace))

    def response(data=None):
        return {"content": [{"type": "text", "text": json.dumps(data or {})}], "isError": False}

    journal.response(
        {
            "event": "readiness_initialize",
            "operation": "search_symbols",
            "arguments": {"name": "__quality_initialize__"},
        },
        response(),
    )
    ready = response()
    ready["structuredContent"] = {
        "capabilities": {
            "coverage": {
                "phase": "ready",
                "total_files": 1,
                "parsed_files": 1,
                "reference_indexed_files": 1,
                "discovery_truncated": False,
            }
        }
    }
    journal.response(
        {"event": "readiness_poll", "operation": "capabilities", "arguments": {}}, ready
    )
    warm = response({"data": {"ranking": {"index": {"status": "ready", "warmup_stage": "ready"}}}})
    journal.response(
        {
            "event": "readiness_semantic",
            "arguments": {
                "query": "__quality_body_initialize__",
                "top_k": 5,
                "max_tokens": 2000,
                "file_filter": "",
            },
        },
        warm,
    )
    pages = []
    for d, b, scope in requests(spec["questions"][0], design):
        args = {"query": "Where alpha beta?", "top_k": d, "max_tokens": b, "file_filter": scope}
        hit = {
            "file_path": "a.py",
            "name": "alpha",
            "chunk_type": "function",
            "score": 1,
            "line": 1,
            "end_line": 1,
            "snippet_start_line": 1,
            "snippet_end_line": 1,
            "snippet": "alpha",
        }
        policy = {
            "producer": "body_index",
            "errors": "replace",
            "newlines": "universal",
            "source_sha256": source_sha,
        }
        journal.response(
            {"event": "source_lineage", "identity": ["a.py", "alpha", "function", 1, 1]}, policy
        )
        page = {
            "data": {
                "results": [hit],
                "ranking": {"index": {"status": "ready", "warmup_stage": "ready"}},
            }
        }
        ref = journal.response(
            {"event": "mcp_response", "tool": "semantic_search", "arguments": args}, response(page)
        )
        row = {
            "pack": "one",
            "arm": "baseline",
            "round": 0,
            "question": "q",
            "kind": "behavior",
            "arguments": args,
            "response_ref": ref,
            "milliseconds": 1,
            "identity": page_identity(page),
            "data_sha256": hashlib.sha256(encode(page["data"])).hexdigest(),
            "control_sha256": hashlib.sha256(encode(control_data(page["data"]))).hexdigest(),
            "judgment": {"files": ["a.py"], "visible": [0]},
        }
        journal.response({"event": "validated_page"}, row)
        pages.append(row)
    journal.response({"event": "gateway_close"}, {"status": "complete"})
    journal.response({"event": "fixture_after"}, source_manifest(workspace))
    journal.response({"event": "origin_end"}, origin)
    report = {
        "status": "complete",
        "pack": "one",
        "arm": "baseline",
        "rounds_completed": 1,
        "pid": 1234,
        "fixture_ref": fixture,
        "pages": pages,
    }
    return evidence, workspace, spec, design, report, engine


def test_actual_source_bound_capture_is_admitted(tmp_path):
    args = capture(tmp_path)
    assert admit_arm(*args, closed=True) == args[4]["pages"]


@pytest.mark.parametrize(
    "damage", ["raw", "summary", "request", "source", "unready", "origin", "late_readiness"]
)
def test_corrupt_or_unready_capture_stops_before_next_arm(tmp_path, damage):
    evidence, workspace, spec, design, report, engine = capture(tmp_path)
    if damage == "summary":
        report["pages"][0]["judgment"]["visible"] = []
    elif damage == "request":
        report["pages"][0]["arguments"]["query"] = "other"
    elif damage == "source":
        (workspace / "a.py").write_bytes(b"beta\n")
    elif damage == "origin":
        (engine / "query_ranking.py").unlink()
    else:
        path = evidence / "journal/events.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        if damage == "raw":
            (evidence / "journal" / report["pages"][0]["response_ref"]["path"]).write_bytes(b"{}")
        elif damage == "unready":
            events = [e for e in events if e["request"]["event"] != "readiness_poll"]
        else:
            index = next(
                i for i, e in enumerate(events) if e["request"]["event"] == "readiness_poll"
            )
            events.append(events.pop(index))
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises((ValueError, KeyError)):
        admit_arm(evidence, workspace, spec, design, report, engine, closed=True)


@pytest.mark.parametrize(
    "field",
    [
        "warmup_seconds",
        "keyword_seconds",
        "importance_seconds",
        "body_seconds",
        "body_indexed_files",
        "status",
        "unknown_seconds",
    ],
)
def test_control_projection_excludes_only_named_timing_fields(field):
    old = {
        "results": [{"file_path": "a.py", "score": 1}],
        "ranking": {"index": {field: 1, "body_index_coverage": 1.0}},
    }
    new = {
        "results": [{"file_path": "a.py", "score": 1}],
        "ranking": {"index": {field: 2, "body_index_coverage": 1.0}},
    }
    same = field in {"warmup_seconds", "keyword_seconds", "importance_seconds", "body_seconds"}
    assert (control_data(old) == control_data(new)) is same
    assert old != new


def test_control_projection_preserves_result_order_and_scores():
    old = {
        "results": [{"file_path": "a.py", "score": 1}, {"file_path": "b.py", "score": 0.5}],
        "ranking": {"index": {"warmup_seconds": 1}},
    }
    changed = {**old, "results": list(reversed(old["results"]))}
    assert control_data(old) != control_data(changed)


def test_fresh_worker_protocol_retains_and_replays_real_toy_gateway_pages(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from eval.quality.runner import REPO

    workspace, evidence = tmp_path / "toy", tmp_path / "capture"
    workspace.mkdir()
    evidence.mkdir()
    source = b'def alpha_beta():\n    return "transitions"\n'
    (workspace / "alpha.py").write_bytes(source)
    sha = hashlib.sha256(source).hexdigest()
    spec = {
        "id": "toy",
        "source_sha256": {"alpha.py": sha},
        "questions": [
            {
                "id": "toy-q",
                "kind": "behavior",
                "query": "Where do alpha beta transitions occur?",
                "evidence": [
                    {
                        "file": "alpha.py",
                        "line": 1,
                        "quote": "def alpha_beta():",
                        "source_sha256": sha,
                    }
                ],
            }
        ],
    }
    design = {
        "rounds": [["baseline", "candidate"], ["candidate", "baseline"], ["baseline", "candidate"]],
        "requests": {
            "depths": [5, 24],
            "budgets": [2000, 8000],
            "scoped_depth": 5,
            "scoped_budget": 2000,
        },
        "pack": spec,
    }
    frozen = tmp_path / "worker.json"
    frozen.write_text(json.dumps(design))
    command = [
        sys.executable,
        "-m",
        "eval.quality.relevance_experiment",
        "--workspace",
        str(workspace),
        "--evidence",
        str(evidence),
        "--spec",
        str(frozen),
        "--arm",
        "baseline",
    ]
    inputs = (
        "".join(json.dumps({"round": n}) + "\n" for n in range(3))
        + json.dumps({"close": True})
        + "\n"
    )
    env = dict(os.environ)
    if "ATTOCODE_EXPERIMENT_ENGINE" not in env:
        from attocode_intel import __file__ as package_path

        env["ATTOCODE_EXPERIMENT_ENGINE"] = str(Path(package_path).parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(env["ATTOCODE_EXPERIMENT_ENGINE"]).parent), str(REPO)]
    )
    child = subprocess.run(
        command, input=inputs, text=True, capture_output=True, cwd=REPO, env=env, timeout=60
    )
    assert child.returncode == 0, child.stderr
    acks = [json.loads(line) for line in child.stdout.splitlines()]
    assert [a["status"] for a in acks] == [
        "ready",
        "round_complete",
        "round_complete",
        "round_complete",
        "complete",
    ]
    assert acks[1:4] == [{"status": "round_complete", "round": n} for n in range(3)]
    report = json.loads((evidence / "pages.json").read_bytes())
    assert acks[0]["pid"] == report["pid"] and report["pid"] != os.getpid()
    pages = admit_arm(
        evidence,
        workspace,
        spec,
        design,
        report,
        Path(env["ATTOCODE_EXPERIMENT_ENGINE"]),
        closed=True,
    )
    assert len(pages) == 15 and all(p["judgment"]["files"] == ["alpha.py"] for p in pages)
