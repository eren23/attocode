"""Frozen file-coverage comparison, with separate persistent engine processes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath

from eval.quality.experiment_evidence import Journal, assert_engine, encode, read_source
from eval.quality.fixture_identity import source_entry, source_manifest
from eval.quality.preview_experiment import page_identity, request_page
from eval.quality.readiness import coverage_ready, wait_ready
from eval.quality.restart_experiment import archive_engine, engine_files, require
from eval.quality.runner import REPO, write_json

DESIGN = REPO / "packages/code-intel/evals/designs/2026-10-23-file-coverage-routed.json"


# These four producer-defined durations differ between fresh engine processes.
CONTROL_TIMINGS = frozenset(
    {"warmup_seconds", "keyword_seconds", "importance_seconds", "body_seconds"}
)


def control_data(data, workspace=None):
    result = dict(data)
    ranking = data.get("ranking")
    if isinstance(ranking, dict) and isinstance(ranking.get("index"), dict):
        result["ranking"] = {
            **ranking,
            "index": {k: v for k, v in ranking["index"].items() if k not in CONTROL_TIMINGS},
        }
    follow = data.get("follow_up")
    args = follow.get("arguments") if isinstance(follow, dict) else None
    if isinstance(args, dict) and "workspace" in args:
        require(
            workspace is not None
            and type(args["workspace"]) is str
            and args["workspace"] == str(Path(workspace).resolve()),
            "search continuation workspace route differs from selected workspace",
        )
        result["follow_up"] = {
            **follow,
            "arguments": {**args, "workspace": "__quality_fixture_workspace__"},
        }
    return result


def requests(question, design):
    c = design["requests"]
    scopes = list(dict.fromkeys(a["file"] for a in question["evidence"]))
    return [(d, b, "") for d in c["depths"] for b in c["budgets"]] + [
        (c["scoped_depth"], c["scoped_budget"], path) for path in scopes
    ]


def judgments(page, spans, question, workspace):
    files, visible = set(), set()
    for hit, source in zip(page["data"]["results"], spans, strict=True):
        path = hit["file_path"]
        anchors = [(i, a) for i, a in enumerate(question["evidence"]) if a["file"] == path]
        if not anchors:
            continue
        files.add(path)
        if source["kind"] != "source":
            continue
        policy = source["policy"]
        text = read_source(workspace / path, errors=policy["errors"], newlines=policy["newlines"])
        lines = text.splitlines(keepends=True)
        for index, anchor in anchors:
            # Quotes are complete source lines with original indentation.
            position = sum(len(line) for line in lines[: anchor["line"] - 1]) + lines[
                anchor["line"] - 1
            ].index(anchor["quote"])
            if any(
                begin <= position and position + len(anchor["quote"]) <= end
                for begin, end in source["spans"]
            ):
                visible.add(index)
    return {"files": sorted(files), "visible": sorted(visible)}


def verify_labels(workspace, spec):
    for path, sha in spec["source_sha256"].items():
        require(
            hashlib.sha256((workspace / path).read_bytes()).hexdigest() == sha,
            "label source changed",
        )
    for q in spec["questions"]:
        for a in q["evidence"]:
            lines = read_source(
                workspace / a["file"], errors="strict", newlines="universal"
            ).splitlines()
            require(
                type(a["line"]) is int
                and 1 <= a["line"] <= len(lines)
                and lines[a["line"] - 1].strip() == a["quote"].strip()
                and spec["source_sha256"][a["file"]] == a["source_sha256"],
                "label anchor changed",
            )


def decide(reports, design):
    pairs, timing = {}, {"baseline": [], "candidate": []}
    require(len(reports) == len(design["packs"]), "missing pack")
    for report, spec in zip(reports, design["packs"], strict=True):
        require(
            report["pack"] == spec["id"] and report["status"] == "complete",
            "pack incomplete or reordered",
        )
        expected = [
            (r, arm, q["id"], d, b, scope)
            for r, arms in enumerate(design["rounds"])
            for arm in arms
            for q in spec["questions"]
            for d, b, scope in requests(q, design)
        ]
        actual = []
        for row in report["pages"]:
            a = row["arguments"]
            key = (
                row["round"],
                row["arm"],
                row["question"],
                a["top_k"],
                a["max_tokens"],
                a["file_filter"],
            )
            actual.append(key)
            pair = (
                spec["id"],
                row["round"],
                row["question"],
                a["top_k"],
                a["max_tokens"],
                a["file_filter"],
            )
            require(row["arm"] not in pairs.setdefault(pair, {}), "duplicate paired page")
            pairs[pair][row["arm"]] = row
            ms = row["milliseconds"]
            require(type(ms) in (int, float) and math.isfinite(ms) and ms >= 0, "invalid latency")
            if not a["file_filter"]:
                timing[row["arm"]].append(ms)
        require(actual == expected, "missing or reordered pages")
    losses, controls, gains = [], [], {}
    for key, arms in pairs.items():
        require(set(arms) == {"baseline", "candidate"}, "unpaired page")
        old, new = arms["baseline"], arms["candidate"]
        for metric in ("files", "visible"):
            lost = set(old["judgment"][metric]) - set(new["judgment"][metric])
            if lost:
                losses.append({"key": key, "metric": metric, "lost": sorted(lost)})
        if (new["kind"] != "behavior" or new["arguments"]["file_filter"]) and old[
            "control_sha256"
        ] != new["control_sha256"]:
            controls.append(key)
        if new["kind"] == "behavior" and key[3] == 5 and not key[5]:
            gained = set(new["judgment"]["files"]) - set(old["judgment"]["files"])
            for path in gained:
                gains.setdefault(key[1], set()).add((key[0], key[2], path))
    # Gains must repeat in every round; settings cannot multiply one observation.
    gate = all(
        len(gains.get(r, set())) >= 2
        and (
            design["stage"] != "validation"
            or (
                len({(x[0], x[1]) for x in gains.get(r, set())}) >= 2
                and {x[0] for x in gains.get(r, set())} == {p["id"] for p in design["packs"]}
            )
        )
        for r in range(len(design["rounds"]))
    )
    require(all(timing.values()), "missing measured queries")
    p95 = {arm: sorted(ms)[math.ceil(0.95 * len(ms)) - 1] for arm, ms in timing.items()}
    latency = p95["candidate"] <= max(100, 1.5 * p95["baseline"])
    return {
        "status": "complete",
        "decision": "retain" if gate and latency and not losses and not controls else "reject",
        "gain_gate": gate,
        "latency_gate": latency,
        "losses": losses,
        "control_changes": controls,
        "gains_by_round": {
            str(r): sorted(gains.get(r, set())) for r in range(len(design["rounds"]))
        },
        "warm_p95_ms": p95,
        "pairs": len(pairs),
        "qualification": "Implementer-authored non-exhaustive labeled file/excerpt coverage; no agent-completion claim.",
    }


def load_blob(journal, ref):
    require(
        isinstance(ref, dict)
        and ref["path"] == f"blobs/{ref['sha256']}.json"
        and len(ref["sha256"]) == 64
        and all(c in "0123456789abcdef" for c in ref["sha256"]),
        "invalid raw ref",
    )
    p = PurePosixPath(ref["path"])
    require(not p.is_absolute() and ".." not in p.parts, "unsafe raw ref")
    raw = (journal / p).read_bytes()
    require(
        len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
        "raw bytes changed",
    )
    return json.loads(raw)


def admit_arm(evidence, workspace, spec, design, observation, engine, *, closed):
    from attocode_intel.output import response_tokens
    from mcp.types import CallToolResult

    from eval.quality.preview_sources import identity, source_spans

    journal = evidence / "journal"
    require(type(observation.get("pid")) is int and observation["pid"] > 0, "missing worker PID")
    receipt = load_blob(journal, observation["fixture_ref"])
    require(source_manifest(workspace) == receipt, "fixture changed")
    verify_labels(workspace, spec)
    policies, pending, pages, runtime = {}, None, [], {}
    initialized, ready, body_ready, did_close = False, False, False, False
    full_count = len(design["rounds"]) * sum(len(requests(q, design)) for q in spec["questions"])
    for event in map(json.loads, (journal / "events.jsonl").read_bytes().splitlines()):
        req, value = event["request"], load_blob(journal, event["response"])
        kind = req["event"]
        require("origin_end" not in runtime, "event after final origin")
        if kind in ("fixture_before", "fixture_after"):
            require(value == receipt and kind not in runtime, "fixture inventory changed/repeated")
            if kind == "fixture_before":
                require(
                    "origin_start" in runtime and not initialized and not pages and not did_close,
                    "late initial fixture identity",
                )
            else:
                require(
                    did_close and len(pages) == full_count and pending is None,
                    "final fixture identity before complete shutdown",
                )
            runtime[kind] = value
        elif kind in ("origin_start", "origin_end"):
            require(
                kind not in runtime and value.get("attocode_intel") == "__init__.py",
                "missing or duplicate origin",
            )
            if kind == "origin_start":
                require(
                    not runtime and not initialized and not pages and not did_close,
                    "late initial origin",
                )
            else:
                require(
                    did_close and "fixture_after" in runtime and len(pages) == full_count,
                    "final origin before complete shutdown",
                )
            for name, path in value.items():
                rel = PurePosixPath(path)
                require(
                    name.startswith("attocode_intel")
                    and not rel.is_absolute()
                    and ".." not in rel.parts
                    and (engine / rel).is_file(),
                    "module outside selected engine",
                )
            runtime[kind] = value
        elif kind == "readiness_initialize":
            require(
                not initialized
                and not pages
                and "origin_start" in runtime
                and "fixture_before" in runtime,
                "late/repeated/unbound initialization",
            )
            require(
                req
                == {
                    "event": "readiness_initialize",
                    "operation": "search_symbols",
                    "arguments": {"name": "__quality_initialize__"},
                },
                "initialization binding changed",
            )
            require(not CallToolResult.model_validate(value).isError, "initialization error")
            initialized = True
        elif kind == "readiness_poll":
            require(initialized and not pages and not ready, "invalid readiness poll order")
            require(
                req == {"event": "readiness_poll", "operation": "capabilities", "arguments": {}},
                "readiness binding changed",
            )
            response = CallToolResult.model_validate(value)
            require(not response.isError, "readiness error")
            ready = coverage_ready(response.structuredContent["capabilities"]["coverage"])
        elif kind == "readiness_semantic":
            require(ready and not pages and not body_ready, "invalid semantic warmup order")
            response = CallToolResult.model_validate(value)
            require(
                not response.isError
                and response_tokens(response) <= 2000
                and req["arguments"]
                == {
                    "query": "__quality_body_initialize__",
                    "top_k": 5,
                    "max_tokens": 2000,
                    "file_filter": "",
                },
                "invalid unscored warmup",
            )
            index = json.loads(response.content[0].text)["data"]["ranking"]["index"]
            body_ready = index["status"] == index.get("warmup_stage") == "ready"
        elif kind == "source_lineage":
            require(
                ready and body_ready and not did_close and pending is None,
                "source lineage out of order",
            )
            key = tuple(req["identity"])
            if value["producer"] != "metadata":
                require(
                    source_entry(receipt, key[0])["sha256"] == value["source_sha256"],
                    "source lineage mismatch",
                )
            policies[key] = value
        elif kind == "mcp_response":
            require(
                ready and body_ready and pending is None and not did_close,
                "scoring before readiness or unvalidated previous page",
            )
            response = CallToolResult.model_validate(value)
            require(
                req["tool"] == "semantic_search"
                and not response.isError
                and response_tokens(response) <= req["arguments"]["max_tokens"],
                "invalid MCP page",
            )
            page = json.loads(response.content[0].text)
            require(
                page["metadata"]["workspace"] == str(Path(workspace).resolve()),
                "MCP workspace differs",
            )
            index = page["data"]["ranking"]["index"]
            require(index["status"] == index["warmup_stage"] == "ready", "unready scored page")
            spans = source_spans(
                page, workspace, [policies[identity(h)] for h in page["data"]["results"]]
            )
            pending = req["arguments"], event["response"], page, spans
            policies = {}
        elif kind == "validated_page":
            require(pending is not None, "summary without raw page")
            args, ref, page, spans = pending
            q = next(q for q in spec["questions"] if q["id"] == value["question"])
            require(
                value["arm"] == observation["arm"]
                and value["pack"] == spec["id"]
                and args["query"] == q["query"]
                and value["kind"] == q["kind"],
                "question/engine mismatch",
            )
            derived = dict(
                value,
                arguments=args,
                response_ref=ref,
                identity=page_identity(page),
                data_sha256=hashlib.sha256(encode(page["data"])).hexdigest(),
                control_sha256=hashlib.sha256(
                    encode(control_data(page["data"], workspace))
                ).hexdigest(),
                judgment=judgments(page, spans, q, workspace),
            )
            require(derived == value, "summary differs from raw/source replay")
            pages.append(value)
            pending = None
        elif kind == "gateway_close":
            require(
                not did_close
                and value["status"] == "complete"
                and pending is None
                and len(pages) == full_count,
                "gateway close failed/repeated/early",
            )
            did_close = True
    require(
        ready and body_ready and pending is None and observation["pages"] == pages,
        "missing or altered pages",
    )
    expected = [
        (r, q["id"], d, b, scope)
        for r in range(observation["rounds_completed"])
        for q in spec["questions"]
        for d, b, scope in requests(q, design)
    ]
    actual = [
        (
            p["round"],
            p["question"],
            p["arguments"]["top_k"],
            p["arguments"]["max_tokens"],
            p["arguments"]["file_filter"],
        )
        for p in pages
    ]
    require(actual == expected, "arm page sequence mismatch")
    require(did_close == closed, "close state mismatch")
    if closed:
        require(
            observation["status"] == "complete"
            and "fixture_after" in runtime
            and "origin_end" in runtime,
            "incomplete final worker identity",
        )
        require(
            runtime["origin_end"].get("attocode_intel.query_ranking") == "query_ranking.py",
            "ranking implementation was not loaded in worker",
        )
    return pages


async def serve(workspace, evidence, spec, design, arm):
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.output import response_tokens

    from eval.quality.preview_sources import SourceTracker

    selected = Path(os.environ["ATTOCODE_EXPERIMENT_ENGINE"])
    journal = Journal(evidence / "journal", 25 * 2**20)
    report = {
        "status": "incomplete",
        "pack": spec["id"],
        "arm": arm,
        "pid": os.getpid(),
        "rounds_completed": 0,
        "pages": [],
    }
    journal.response({"event": "origin_start"}, assert_engine(selected))
    receipt = source_manifest(workspace)
    report["fixture_ref"] = journal.response({"event": "fixture_before"}, receipt)
    verify_labels(workspace, spec)
    gateway = OperationGateway(str(workspace), "daily", watch=False)
    tracker = SourceTracker(workspace, journal)
    try:
        report["readiness"] = await wait_ready(
            gateway,
            journal,
            poll_seconds=design.get("readiness", {"poll_seconds": 1.0})["poll_seconds"],
        )
        warm_started = time.monotonic()
        arguments = {
            "query": "__quality_body_initialize__",
            "top_k": 5,
            "max_tokens": 2000,
            "file_filter": "",
        }
        while True:
            response = await gateway.execute_mcp("semantic_search", arguments)
            journal.response(
                {"event": "readiness_semantic", "arguments": arguments},
                response.model_dump(mode="json"),
            )
            require(
                not response.isError and response_tokens(response) <= 2000,
                "semantic warmup error/budget",
            )
            index = json.loads(response.content[0].text)["data"]["ranking"]["index"]
            if index["status"] == index.get("warmup_stage") == "ready":
                break
            await asyncio.sleep(0.1)
        report["semantic_warmup_seconds"] = time.monotonic() - warm_started
        write_json(evidence / "pages.json", report)
        print(json.dumps({"status": "ready", "pid": os.getpid()}), flush=True, file=sys.__stdout__)
        while True:
            command = json.loads(await asyncio.to_thread(sys.stdin.readline))
            if command == {"close": True}:
                require(report["rounds_completed"] == len(design["rounds"]), "early close")
                break
            number = command["round"]
            require(number == report["rounds_completed"], "repeated/reordered round")
            for question in spec["questions"]:
                for depth, budget, scope in requests(question, design):
                    args = {
                        "query": question["query"],
                        "top_k": depth,
                        "max_tokens": budget,
                        "file_filter": scope,
                    }
                    page, ref, ms, spans = await request_page(gateway, tracker, journal, args)
                    require(spans is not None, "unready scored page")
                    row = {
                        "pack": spec["id"],
                        "round": number,
                        "arm": arm,
                        "question": question["id"],
                        "kind": question["kind"],
                        "arguments": args,
                        "response_ref": ref,
                        "milliseconds": ms,
                        "identity": page_identity(page),
                        "data_sha256": hashlib.sha256(encode(page["data"])).hexdigest(),
                        "control_sha256": hashlib.sha256(
                            encode(control_data(page["data"], workspace))
                        ).hexdigest(),
                        "judgment": judgments(page, spans, question, workspace),
                    }
                    journal.response({"event": "validated_page"}, row)
                    report["pages"].append(row)
                    write_json(evidence / "pages.json", report)
            report["rounds_completed"] += 1
            write_json(evidence / "pages.json", report)
            print(
                json.dumps({"status": "round_complete", "round": number}),
                flush=True,
                file=sys.__stdout__,
            )
    finally:
        await gateway.close()
        journal.response({"event": "gateway_close"}, {"status": "complete"})
    require(source_manifest(workspace) == receipt, "worker fixture changed")
    journal.response({"event": "fixture_after"}, receipt)
    journal.response({"event": "origin_end"}, assert_engine(selected))
    report["status"] = "complete"
    write_json(evidence / "pages.json", report)
    print(json.dumps({"status": "complete"}), flush=True, file=sys.__stdout__)


def validate_development_gate(proof, design, protocol_sha256):
    """Accept only the byte-bound independent admission of this development."""
    require(
        proof.get("outcome") == "passed" and proof.get("stage") == "development",
        "missing successful development admission",
    )
    require(
        proof.get("public_design_sha256") == protocol_sha256
        and proof.get("baseline_commit") == design["baseline_commit"]
        and proof.get("candidate_sha256") == design["candidate_sha256"],
        "development protocol or candidate differs",
    )
    report, run = proof["report"], proof["run"]
    require(
        report["identity"]["commit"] == run["head_sha"]
        and report["identity"]["github_run_id"] == str(run["id"])
        and run["status"] == "completed"
        and run["conclusion"] == "success"
        and run["run_attempt"] == 1,
        "development run identity differs",
    )
    require(
        report["status"] == "complete"
        and report["cleanup_verified"]
        and report["owned_scratch_removed"]
        and report["limits"] == design["limits"]
        and report["seconds"] < design["limits"]["seconds"],
        "development is incomplete or outside the frozen limit",
    )
    supervision = report["supervision"]
    require(
        supervision["status"] == "passed"
        and supervision["exit_code"] == 0
        and supervision["cleanup_verified"]
        and not supervision["log_truncated"]
        and supervision["peak_rss_bytes"] < design["limits"]["rss_bytes"]
        and supervision["peak_disk_bytes"] < design["limits"]["disk_bytes"]
        and supervision["peak_evidence_bytes"] < design["limits"]["evidence_bytes"],
        "development resource or cleanup admission failed",
    )
    decision = proof["decision"]
    require(
        decision["status"] == "complete"
        and decision["decision"] == "retain"
        and decision["gain_gate"] is True
        and decision["latency_gate"] is True
        and decision["losses"] == []
        and decision["control_changes"] == [],
        "development did not pass every quality gate",
    )
    require(
        proof.get("all_archive_extracted_bytes_equal") is True
        and proof.get("all_raw_source_origin_order_replayed") is True,
        "development raw/source admission is missing",
    )
    for value in (proof.get("archive_sha256"), proof.get("operator_sha256")):
        require(
            type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            "missing bound development artifact or verifier",
        )


def require_frozen_inputs(previous, current, mutable):
    previous = {name: sha for name, sha in previous.items() if name not in mutable}
    current = {name: sha for name, sha in current.items() if name not in mutable}
    require(previous == current, "inputs changed after development")


def selected_stage(design, frozen, protocol_sha256):
    stage = frozen.get("stage")
    require(stage in {"development", "validation"}, "undeclared relevance stage")
    if stage == "development":
        require("development_admission" not in frozen, "development cannot adopt prior admission")
        return stage
    gate = frozen["development_admission"]
    relative = PurePosixPath(gate["path"])
    require(
        not relative.is_absolute()
        and ".." not in relative.parts
        and str(relative).startswith("packages/code-intel/evals/results/"),
        "unsafe development admission path",
    )
    raw = (REPO / relative).read_bytes()
    require(
        len(raw) < 4 * 2**20 and hashlib.sha256(raw).hexdigest() == gate["sha256"],
        "development admission bytes changed",
    )
    proof = json.loads(raw)
    validate_development_gate(proof, design, protocol_sha256)
    roots = [
        "eval",
        "packages/code-intel",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/intelligence-experiments.yml",
    ]
    names = subprocess.check_output(["git", "ls-files", "-z", "--", *roots]).decode().split("\0")
    current = {
        name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in names if name
    }
    require_frozen_inputs(
        proof["report"]["identity"]["files"],
        current,
        {"eval/quality/experiments/preview.json", str(relative)},
    )
    return stage


def run(root):
    from eval.quality.corpus import materialize

    frozen = json.loads((REPO / "eval/quality/experiments/preview.json").read_bytes())
    raw = DESIGN.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == frozen["design_sha256"], "design bytes changed")
    design = json.loads(raw)
    stage = selected_stage(design, frozen, hashlib.sha256(raw).hexdigest())
    selected = {**design, **design["stages"][stage], "stage": stage}
    evidence, work = root / "evidence/relevance", root / "work/relevance"
    evidence.mkdir()
    work.mkdir(parents=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    engines = {
        a: archive_engine(c, work / "engines" / a)
        for a, c in [("baseline", design["baseline_commit"]), ("candidate", head)]
    }
    identities = {a: engine_files(e) for a, e in engines.items()}
    changed = sorted(
        p
        for p in identities["baseline"].keys() | identities["candidate"].keys()
        if identities["baseline"].get(p) != identities["candidate"].get(p)
    )
    require(
        changed == ["query_ranking.py"]
        and identities["candidate"]["query_ranking.py"] == design["candidate_sha256"],
        "candidate scope or source changed",
    )
    write_json(
        evidence / "freeze.json",
        {
            "engines": identities,
            "baseline": design["baseline_commit"],
            "head": head,
            "design_sha256": hashlib.sha256(raw).hexdigest(),
        },
    )
    reports, pids = [], set()
    write_json(
        evidence / "decision.json",
        {
            "status": "incomplete",
            "decision": None,
            "stage": stage,
            "expected_packs": [p["id"] for p in selected["packs"]],
        },
    )
    for spec in selected["packs"]:
        dest, fixture, receipt = evidence / spec["id"], work / spec["id"], {}
        dest.mkdir()
        tree = materialize(spec, fixture, root / "cache/relevance-source", receipt=receipt)
        require(source_manifest(fixture) == receipt, "pinned fixture mismatch")
        write_json(
            dest / "fixture.json",
            {"tree": tree, "receipt": receipt, "repo": spec["repo"], "commit": spec["commit"]},
        )
        children, logs, workspaces = {}, {}, {}
        combined = {"pack": spec["id"], "status": "incomplete", "pages": []}
        write_json(dest / "combined.json", combined)
        spec_path = dest / "worker-design.json"
        write_json(spec_path, {**selected, "pack": spec})
        try:
            for arm in ("baseline", "candidate"):
                ws, ev, engine = work / (spec["id"] + "-" + arm), dest / arm, engines[arm]
                ev.mkdir()
                shutil.copytree(fixture, ws, symlinks=True)
                workspaces[arm] = ws
                logs[arm] = (ev / "process.log").open("xb")
                env = dict(
                    os.environ,
                    PYTHONPATH=os.pathsep.join([str(engine.parent), str(REPO)]),
                    ATTOCODE_EXPERIMENT_ENGINE=str(engine),
                )
                command = [
                    sys.executable,
                    "-m",
                    "eval.quality.relevance_experiment",
                    "--workspace",
                    str(ws),
                    "--evidence",
                    str(ev),
                    "--spec",
                    str(spec_path),
                    "--arm",
                    arm,
                ]
                child = subprocess.Popen(
                    command,
                    cwd=REPO,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=logs[arm],
                    text=True,
                )
                children[arm] = child
                ack = json.loads(child.stdout.readline())
                require(
                    ack["status"] == "ready" and ack["pid"] == child.pid and child.pid not in pids,
                    "worker readiness/PID failed",
                )
                pids.add(child.pid)
                admit_arm(
                    ev,
                    ws,
                    spec,
                    selected,
                    json.loads((ev / "pages.json").read_bytes()),
                    engine,
                    closed=False,
                )
            for number, arms in enumerate(design["rounds"]):
                for arm in arms:
                    child, ev = children[arm], dest / arm
                    child.stdin.write(json.dumps({"round": number}) + "\n")
                    child.stdin.flush()
                    require(
                        json.loads(child.stdout.readline())
                        == {"status": "round_complete", "round": number},
                        "round worker failed",
                    )
                    observed = json.loads((ev / "pages.json").read_bytes())
                    pages = admit_arm(
                        ev, workspaces[arm], spec, selected, observed, engines[arm], closed=False
                    )
                    combined["pages"].extend(p for p in pages if p["round"] == number)
                    write_json(dest / "combined.json", combined)
            for arm, child in children.items():
                child.stdin.write(json.dumps({"close": True}) + "\n")
                child.stdin.flush()
                require(
                    json.loads(child.stdout.readline()) == {"status": "complete"}
                    and child.wait(timeout=10) == 0,
                    "worker close failed",
                )
                ev = dest / arm
                admit_arm(
                    ev,
                    workspaces[arm],
                    spec,
                    selected,
                    json.loads((ev / "pages.json").read_bytes()),
                    engines[arm],
                    closed=True,
                )
                require(
                    engine_files(engines[arm]) == identities[arm]
                    and source_manifest(workspaces[arm]) == receipt,
                    "worker engine/source changed",
                )
            combined["status"] = "complete"
            write_json(dest / "combined.json", combined)
            reports.append(combined)
            write_json(
                evidence / "decision.json",
                {
                    "status": "incomplete",
                    "decision": None,
                    "completed_packs": [r["pack"] for r in reports],
                },
            )
        finally:
            for child in children.values():
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                child.stdin.close()
                child.stdout.close()
            for log in logs.values():
                log.close()
            for ws in workspaces.values():
                shutil.rmtree(ws)
            require(source_manifest(fixture) == receipt, "fixture changed before cleanup")
            shutil.rmtree(fixture)
    write_json(evidence / "decision.json", decide(reports, selected))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--arm", choices=["baseline", "candidate"], required=True)
    args = parser.parse_args()
    frozen = json.loads(args.spec.read_bytes())
    with redirect_stdout(sys.stderr):
        asyncio.run(serve(args.workspace, args.evidence, frozen["pack"], frozen, args.arm))
