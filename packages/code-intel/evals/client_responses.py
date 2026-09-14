"""Measure matched MCP queries as actually exposed in each client's private trace."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens
from study import manifest_for, servers_for, write_json
from study_clients import CLIENTS, invoke, parse_events, preflight, subscription_env
from workflows import SCENARIOS


def source_hash(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def queries(spec):
    return [("search_symbols", {"name": spec["symbol"]}),
            ("cross_references", {"symbol_name": spec["symbol"]}),
            ("dependencies", {"path": spec["file"]}),
            ("suggest_tests", {"files": [spec["file"]]}),
            ("search_symbols", {"name": "attocode_deliberately_absent_9273"})]


def collect(parsed, spec):
    """Only count results with an observed, matching tool call. Missing output is not zero."""
    output = {row["id"]: row["content"] for row in parsed["tool_results"]}
    rows = [{"tokens": 0, "responses": []} for _ in queries(spec)]
    for call in parsed["tool_calls"]:
        arguments = call.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                continue
        for i, (name, expected) in enumerate(queries(spec)):
            if (call["name"].endswith("__" + name) and all(arguments.get(k) == v for k, v in expected.items())
                    and call["id"] in output and output[call["id"]] is not None):
                content = output[call["id"]]
                rows[i]["tokens"] += count_tokens(json.dumps(content))
                rows[i]["responses"].append(content)
    return rows


def envelopes(value):
    if isinstance(value, str):
        try:
            yield from envelopes(json.loads(value))
        except ValueError:
            pass
    elif isinstance(value, list):
        for item in value:
            yield from envelopes(item)
    elif isinstance(value, dict):
        if "metadata" in value and ("data" in value or "result" in value):
            yield value
        elif "structuredContent" in value and value["structuredContent"]:
            yield from envelopes(value["structuredContent"])
        else:
            for key in ("content", "text", "result", "success"):
                if key in value:
                    yield from envelopes(value[key])


def preserved(before, after, spec, index):
    a = list(envelopes(before["responses"]))
    b = list(envelopes(after["responses"]))
    if not a or not b or any(not item.get("metadata", {}).get("workspace") for item in b):
        return False
    if index == 1:
        def normalize(items):
            return {(r["file_path"], r["line"], r["ref_kind"], r["source"])
                    for item in items for r in item.get("data", {}).get("references", [])}
        return normalize(a) == normalize(b) and not b[-1].get("data", {}).get("next_cursor")
    if index == 4:
        return a[-1].get("data") == b[-1].get("data") == []
    anchor = spec["file"] if index == 0 else spec["importer"] if index == 2 else spec["test"]
    return anchor in json.dumps(b) if anchor else True


def run(args):
    manifest = manifest_for(args.study)
    baseline_hash = source_hash(args.baseline_src)
    copied = args.study / "response-baseline"
    if not copied.exists():
        shutil.copytree(args.baseline_src, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if source_hash(copied) != baseline_hash:
        raise ValueError("Response baseline changed; start a new study")
    env, rng = subscription_env(), random.Random(9273)
    results = []
    for client in args.clients or CLIENTS:
        for spec in SCENARIOS:
            lanes = ["baseline", "candidate"]
            rng.shuffle(lanes)
            parsed = {}
            for lane in lanes:
                directory = args.study / "response-runs" / f"{client}-{spec['repo']}-{lane}"
                saved = directory / "measured.json"
                if saved.exists():
                    parsed[lane] = json.loads(saved.read_text())
                    continue
                quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
                status = preflight(client, quota, env)
                if not status["ready"]:
                    print(json.dumps({"client": client, "blocked": status}))
                    return
                if directory.exists():
                    raise ValueError("An interrupted response trial exists; preserve it and start a new study")
                root = directory / "repository"
                shutil.copytree(args.study / "sources" / spec["repo"], root,
                                ignore=shutil.ignore_patterns("node_modules", "target", "__pycache__", ".attocode", ".serena"))
                servers = servers_for(manifest, args.study, root, "intel_base", directory, client)
                if lane == "baseline":
                    servers["intelligence"]["env"]["PYTHONPATH"] = str(copied)
                prompt = ("This is a fixed-query response measurement, not an open-ended coding task. "
                          "Call exactly these intelligence tools with these arguments, once each: " + json.dumps(queries(spec)) +
                          ". For cross_references only, follow next_cursor until null, retaining the original query arguments. "
                          "Do not read or edit other files, run shell commands, record memory, or delegate. "
                          "Return a short JSON summary after the calls; leave unknown definition/usage fields empty.")
                result = invoke(client, manifest["models"][client], root, directory, servers, prompt, 600, env)
                if result["exit_code"] or result["timed_out"] or result["quota_exhausted"]:
                    write_json(directory / "failed.json", result)
                    print(json.dumps({"client": client, "repo": spec["repo"], "failed": True}))
                    return
                parsed[lane] = collect(parse_events(client, (directory / "trace.jsonl").read_text()), spec)
                write_json(saved, parsed[lane])
            for i, (a, b) in enumerate(zip(parsed["baseline"], parsed["candidate"], strict=True)):
                results.append({"id": f"{client}:{spec['repo']}:{i}", "before": a["tokens"], "after": b["tokens"],
                                "evidence_preserved": preserved(a, b, spec, i)})
    destination = args.study / "client-response-volume.json"
    prior = json.loads(destination.read_text()) if destination.exists() else {}
    rows = {row["id"]: row for row in prior.get("rows", [])}
    rows.update({row["id"]: row for row in results})
    write_json(destination, {"measurement": "client_visible", "baseline_engine_sha256": baseline_hash,
                             "candidate_engine_sha256": manifest["engine_sha256"], "rows": list(rows.values())})
    print(json.dumps({"report": str(destination), "queries": len(rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--baseline-src", type=Path, required=True)
    parser.add_argument("--quota", type=Path)
    parser.add_argument("--clients", nargs="+", choices=CLIENTS)
    run(parser.parse_args())
