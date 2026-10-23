"""Pinned source-only workflow packs and the existing ranking gate.

Existing historical trees/clones are read-only inputs. New indexes and copies
are disposable. No repository tests, install scripts, or models are executed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.matrix import run as matrix
from eval.quality.evidence import reusable_rows, select_packs, summarize
from eval.quality.runner import REPO, fingerprint, stop_group, write_json
from eval.quality.sources import read_tree, scoped_entries

PACK = Path(__file__).with_name("workflows.yaml")
HISTORY = Path.home() / "Documents/AI/attocode-evals/matrix"
CLONES = Path.home() / "Documents/ai/benchmark-repos"
PACK_SECONDS = 180


def definition_matches(row, spec):
    """Require exact identity, accepting adapters that retain qualified names."""
    name, expected = row["name"], spec["symbol"]
    return row["file_path"] == spec["file"] and (
        name in {expected, expected.split(".")[-1]}
        or ("." not in expected and name.split(".")[-1] == expected))


def materialize(spec, destination, cache, *, receipt=None):
    name, commit = spec["repo"], spec["commit"]
    historical = matrix._tree_file(HISTORY, name, commit)
    if historical.exists():
        tree = json.loads(historical.read_text())
        tree = {**tree, "entries": scoped_entries(tree["entries"], spec)}
        blob_root = HISTORY
    else:
        source = REPO if spec["id"] == "frontend" else CLONES / spec["id"]
        if (source / ".git").exists():
            tree = read_tree(source, commit, cache, spec, remote=False)
        else:
            if os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1":
                raise ValueError(f"Missing pinned source {name}@{commit}; enable downloads on the remote worker")
            with tempfile.TemporaryDirectory(prefix="quality-fetch-") as tmp:
                clone = matrix._remote(name, Path(tmp))
                matrix._git(clone, "fetch", "-q", "--depth", "1", "--filter=blob:limit=1000001", "--no-tags", "origin", commit)
                tree = read_tree(clone, commit, cache, spec, remote=True)
        blob_root = cache
    if tree.get("error"):
        raise ValueError(tree["error"])
    if receipt is not None:
        from eval.quality.fixture_identity import pinned_manifest
        receipt.update(pinned_manifest(blob_root, tree))
    matrix._materialize(blob_root, tree, destination)
    return tree.get("tree")


async def ready_search(gateway, arguments, *, timeout=90):
    """Wait only on an explicit warming response, recording cold-start cost."""
    started = time.monotonic()
    warming = 0
    while True:
        response = await gateway.execute_mcp("semantic_search", arguments)
        if response_tokens(response) > arguments["max_tokens"]:
            raise ValueError("Search warmup response exceeded its output budget")
        decoded = json.loads(response.content[0].text)
        status = decoded.get("data", {}).get("ranking", {}).get("index", {}).get("status")
        if response.isError or status != "warming":
            return response, {"warming_responses": warming,
                              "warmup_seconds": time.monotonic() - started if warming else 0}
        warming += 1
        if time.monotonic() - started >= timeout:
            index = decoded.get("data", {}).get("ranking", {}).get("index", {})
            raise TimeoutError(f"Search index still warming after {timeout} seconds; index={json.dumps(index)}")
        await asyncio.sleep(.1)


async def evaluate(root, spec, *, observations=None, checkpoint=None):
    source = root / spec["file"]
    content = source.read_text()
    if spec["anchor"] not in content or (spec.get("source_sha256") and
            hashlib.sha256(content.encode()).hexdigest() != spec["source_sha256"]):
        raise ValueError("Pinned source definition changed: invalid fixture")
    line = content[:content.index(spec["anchor"])].count("\n") + 1
    selection = {"symbol_name": spec["symbol"], "file_path": spec["file"], "line": line}
    gateway = OperationGateway(str(root), "daily", watch=False)
    rows = []
    from attocode_intel._internal.integrations.context.ts_parser import is_available
    unavailable = (spec.get("parser_requirement") == "optional"
                   and not is_available(spec["language"]))
    from attocode_intel._internal.integrations.utilities.ignore import IgnoreManager
    source_excluded = (IgnoreManager(root).is_ignored(spec["file"])
                       or any(part.startswith('.') for part in Path(spec["file"]).parts))
    async def check(name, tool, arguments, predicate, *, paginate=False, limited=None):
        start = time.monotonic()
        warmup = {}
        if tool == "semantic_search":
            response, warmup = await ready_search(gateway, {"max_tokens": 4000, **arguments})
        else:
            response = await gateway.execute_mcp(tool, {"max_tokens": 4000, **arguments})
        decoded = json.loads(response.content[0].text)
        data = decoded.get("data", {})
        pages = [decoded]
        within_budget = response_tokens(response) <= 4000
        while paginate and not predicate(data) and data.get("next_cursor") and len(pages) < 10:
            response = await gateway.execute_mcp(tool, {"max_tokens": 4000, **arguments, "cursor": data["next_cursor"]})
            decoded = json.loads(response.content[0].text)
            data = decoded.get("data", {})
            pages.append(decoded)
            within_budget = within_budget and response_tokens(response) <= 4000
            if response.isError:
                break
        passed = not response.isError and within_budget and bool(predicate(data))
        outcome = "failed" if not passed else "limited" if limited else "passed"
        if unavailable and name in {"definition", "source", "restart"} and not passed:
            outcome = "unsupported"
            limited = "Optional grammar is not installed/cached; no acquisition during navigation"
        if source_excluded and name in {"definition", "source", "scoped_search", "restart"} and not passed:
            outcome = "unsupported"
            limited = "Labeled source is excluded by workspace discovery policy; explicit project inclusion is required"
        rows.append({"name": name, "passed": outcome == "passed", "outcome": outcome,
                     "contract_passed": passed, "limitation": limited, "seconds": time.monotonic() - start,
                     "response": decoded, "tool": tool, "pages_requested": len(pages), **warmup})
        if checkpoint:
            checkpoint(rows, observations or [])
        return data
    try:
        definitions = await check("definition", "search_symbols", {"name": spec["symbol"]},
                    lambda d: any(definition_matches(r, spec) for r in d))
        # Attributes/decorators can precede the declaration's name. Follow the
        # returned selection contract, while requiring it to contain the native
        # source anchor; never substitute a different same-named definition.
        choices = [d for d in definitions if definition_matches(d, spec)]
        if len(choices) > 1:
            choices = [d for d in choices if d["start_line"] <= line <= d["end_line"]]
        if len(choices) == 1:
            selection["line"] = choices[0]["start_line"]
        await check("source", "inspect_symbol", selection,
                    lambda d: d.get("status") == "found" and d["definition"]["file_path"] == spec["file"]
                    and bool(d.get("source", {}).get("text")))
        await check("scoped_search", "semantic_search", {"query": spec.get("query", spec["symbol"]), "file_filter": spec["file"], "top_k": 5},
                    lambda d: bool(d.get("results")) and all(r["file_path"] == spec["file"] for r in d["results"]))
        await check("caller_syntax", "cross_references", {"symbol_name": spec["symbol"]},
                    lambda d: (any(r["file_path"] == spec["caller"] for r in d.get("references", []))
                               if spec["caller"] else not d.get("absence_proven", False)), paginate=True,
                    limited=None if spec["caller"] else "No independently labeled caller")
        await check("dependencies", "dependencies", {"path": spec["file"]},
                    lambda d: spec["importer"] in d.get("imported_by", []) if spec["importer"] else not d.get("absence_proven", False),
                    limited=None if spec["importer"] else "No labeled importer; only uncertainty reporting is checked")
        await check("impact", "impact_analysis", {"changed_files": [spec["file"]]},
                    lambda d: not d.get("absence_proven", False) and
                    (not spec["importer"] or spec["importer"] in d.get("impacted_files", []) or
                     any(spec["importer"] in layer["files"] for layer in d.get("layers", []))),
                    limited=None if spec["importer"] else "No labeled impacted file; only uncertainty reporting is checked")
        await check("tests", "suggest_tests", {"files": [spec["file"]]},
                    lambda d: not d.get("absence_proven", False) and
                    (not spec["test"] or any(r["file_path"] == spec["test"] for r in d.get("candidates", []))),
                    limited=None if spec["test"] else "No labeled test; only uncertainty reporting is checked")
        if observations is not None:
            for question in spec.get("queries", []):
                for label in question["evidence"]:
                    path = (root / label["file"]).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError("Query evidence escapes source scope")
                    text = path.read_text()
                    if hashlib.sha256(text.encode()).hexdigest() != label["source_sha256"]:
                        raise ValueError("Query evidence source changed: " + label["file"])
                    if label["quote"] not in text:
                        raise ValueError("Query evidence anchor missing: " + label["file"])
                started = time.monotonic()
                response, warmup = await ready_search(gateway, {
                    "query": question["query"], "top_k": 24, "max_tokens": 8000})
                decoded = json.loads(response.content[0].text)
                if response.isError:
                    raise RuntimeError("Unscoped retrieval failed: " + question["id"])
                files = list(dict.fromkeys(hit["file_path"] for hit in decoded.get("data", {}).get("results", [])))
                expected = {label["file"] for label in question["evidence"]}
                ranks = [i + 1 for i, path in enumerate(files) if path in expected]
                observations.append({"id": question["id"], "query": question["query"],
                                     "ranked_files": files, "labeled_files": sorted(expected),
                                     "first_labeled_rank": min(ranks) if ranks else None,
                                     "hit_at_5": any(rank <= 5 for rank in ranks),
                                     "hit_at_24": any(rank <= 24 for rank in ranks),
                                     "delivered_files": len(files),
                                     "metadata": decoded.get("metadata", {}),
                                     "seconds": time.monotonic() - started, **warmup})
                if checkpoint:
                    checkpoint(rows, observations)
        await gateway.close()
        gateway = OperationGateway(str(root), "daily", watch=False)
        await check("restart", "inspect_symbol", selection,
                    lambda d: d.get("status") == "found" and d["definition"]["file_path"] == spec["file"])
    finally:
        await gateway.close()
    return rows


def frozen_ranking(destination):
    """Give the existing clean-tree gate a disposable commit of the local input.

    The user's checkout and history stay untouched. The report binds this
    temporary commit to the actual source hash, not to a claimed upstream SHA.
    """
    for relative in ("eval/matrix", "eval/meta_harness", "packages/code-intel/src"):
        shutil.copytree(REPO / relative, destination / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    destination.mkdir(exist_ok=True)
    for name in ("metrics.py", "harness.py"):
        shutil.copyfile(REPO / "eval" / name, destination / "eval" / name)
    release_gate = Path("packages/code-intel/evals/release_gate.py")
    (destination / release_gate).parent.mkdir(parents=True)
    shutil.copyfile(REPO / release_gate, destination / release_gate)
    for command in (["init", "-q"], ["add", "."], ["commit", "-qm", "Frozen local quality input"]):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
                        "-c", "user.name=Quality runner", "-c", "user.email=quality@localhost", "-C", str(destination), *command], check=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(destination / "packages/code-intel/src") + os.pathsep + str(destination)
    cache = destination / ".cache"
    if os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1":
        # Existing gate snapshots can be read without duplicating the 14 GB
        # historical blob pool. Only the required blobs are copied.
        from eval.matrix.ci import instances
        for inst in instances():
            tree_path = matrix._tree_file(HISTORY, inst.repo, inst.base_commit)
            if not tree_path.exists():
                raise ValueError("Ranking snapshot unavailable locally; run broad on the remote worker")
            tree = json.loads(tree_path.read_text())
            target = matrix._tree_file(cache, inst.repo, inst.base_commit)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tree_path, target)
            for entry in tree.get("entries", []):
                if matrix._stored(entry):
                    blob = matrix._blob_file(cache, entry[2])
                    if not blob.exists():
                        blob.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(matrix._blob_file(HISTORY, entry[2]), blob)
    code = subprocess.call([sys.executable, "-m", "eval.matrix.run", "ci", "--cache", str(cache)], cwd=destination, env=env)
    return {"passed": code == 0, "exit_code": code, "frozen_local_snapshot": True}


def evidence_identity():
    """Bind resumes to actual implementation, fixture, dependency and runtime inputs."""
    grammar_identity = None
    try:
        import tree_sitter_language_pack as pack
        if callable(getattr(pack, "download", None)):
            cache = Path(pack.cache_dir())
            digest = hashlib.sha256()
            for path in sorted(cache.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.suffix in {".so", ".dylib", ".dll"}:
                    digest.update(str(path.relative_to(cache)).encode() + b"\0")
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
            grammar_identity = {
                "languages": sorted(pack.downloaded_languages()),
                "cache_sha256": digest.hexdigest(),
            }
    except ImportError:
        pass
    return {
        "source_sha256": fingerprint([REPO / "packages/code-intel/src"]),
        "harness_sha256": fingerprint([REPO / "eval/quality", REPO / "eval/matrix", REPO / "uv.lock"]),
        "fixture_sha256": fingerprint([REPO / "packages/code-intel/tests"]),
        "pack_sha256": hashlib.sha256(PACK.read_bytes()).hexdigest(),
        "python": sys.version, "platform": platform.platform(),
        "optional_grammars": grammar_identity,
        "dependencies": sorted({(d.metadata["Name"].lower(), d.version)
                                for d in importlib.metadata.distributions() if d.metadata["Name"]}),
        "settings": {k: os.environ.get(k) for k in (
            "ATTOCODE_INTEL_PRECISION", "ATTOCODE_INTEL_BROAD_RERANK",
            "ATTOCODE_INTEL_RANKING_PROVIDER", "ATTOCODE_INTEL_RANKING_ALLOW_REMOTE",
            "ATTOCODE_EMBEDDING_MODEL", "ATTOCODE_NL_EMBEDDING_MODE", "ATTOCODE_LOCAL_ONLY")},
    }


def evaluate_isolated(root, spec, directory):
    """A pathological parser cannot consume the entire matrix's time budget."""
    input_path, output_path = directory / "spec.json", directory / "worker.json"
    write_json(input_path, spec)
    process = subprocess.Popen([sys.executable, "-m", "eval.quality.corpus", "--worker", str(root),
                                "--spec", str(input_path), "--output", str(output_path)],
                               start_new_session=True)
    reason = None
    try:
        code = process.wait(timeout=PACK_SECONDS)
        if code or not output_path.is_file():
            reason = f"Workflow worker failed (exit {code})"
    except subprocess.TimeoutExpired:
        reason = f"Workflow pack exceeded {PACK_SECONDS} seconds"
    finally:
        stop_group(process)
    result = json.loads(output_path.read_text()) if output_path.is_file() else {"checks": [], "retrieval": []}
    if reason:
        result.update(status="incomplete", error=reason)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ranking", action="store_true")
    parser.add_argument("--pack", action="append", default=[])
    parser.add_argument("--shard")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--spec", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not args.spec:
            parser.error("Worker requires a source specification")
        observations = []
        def checkpoint(checks, retrieval):
            write_json(args.output, {"checks": checks, "retrieval": retrieval})
        try:
            checks = asyncio.run(evaluate(args.worker, json.loads(args.spec.read_text()),
                                          observations=observations, checkpoint=checkpoint))
        except Exception as exc:
            # Preserve diagnostics even before the parent log reader reaches EOF.
            result = json.loads(args.output.read_text()) if args.output.is_file() else {
                "checks": [], "retrieval": observations,
            }
            result["worker_error"] = {"type": type(exc).__name__, "message": str(exc)[:4000]}
            write_json(args.output, result)
            raise
        write_json(args.output, {"checks": checks, "retrieval": observations})
        return 0
    if args.ranking and (args.pack or args.shard or args.resume):
        parser.error("Ranking uses its unchanged complete frozen gate")
    specs = yaml.safe_load(PACK.read_text())["repositories"]
    selected = select_packs(specs, args.pack, args.shard)
    # Round-trip normalizes tuple-valued dependency rows for JSON resume comparisons.
    identity = json.loads(json.dumps(evidence_identity()))
    selected_ids = [s["id"] for s in selected]
    resumed = reusable_rows(json.loads(args.resume.read_text()), identity, selected_ids) if args.resume else {}
    report = {"schema_version": 2, "identity": identity,
              "pack_sha256": identity["pack_sha256"], "repositories": [],
              "manifest_packs": sorted(s["id"] for s in specs), "selected_packs": selected_ids,
              "model_runs": 0, "scope": "Development evidence anchors, not exhaustive recall or agent benefit"}
    report["git_version"] = subprocess.check_output(["git", "--version"], text=True).strip()
    workspace_root = None
    try:
        with tempfile.TemporaryDirectory(prefix="quality-corpus-") as tmp:
            workspace_root = Path(tmp)
            if args.ranking:
                report.update(frozen_ranking(Path(tmp) / "ranking"))
            else:
                for spec in selected:
                    if spec["id"] in resumed:
                        report["repositories"].append(resumed[spec["id"]])
                        write_json(args.output, report)
                        continue
                    row = {"id": spec["id"], "revision": spec["commit"], "language": spec["language"]}
                    row["expected_questions"] = [q["id"] for q in spec.get("queries", [])]
                    row.update(status="incomplete", passed=False, phase="materialize")
                    report["repositories"].append(row)
                    write_json(args.output, report)
                    with tempfile.TemporaryDirectory(prefix=spec["id"] + "-", dir=tmp) as workspace:
                        try:
                            started = time.monotonic()
                            # Blob copies belong to this pack, not the entire matrix.
                            with tempfile.TemporaryDirectory(prefix="blobs-", dir=tmp) as cache:
                                row["tree"] = materialize(spec, Path(workspace), Path(cache))
                            row["setup_seconds"] = time.monotonic() - started
                            row["phase"] = "evaluate"
                            write_json(args.output, report)
                            with tempfile.TemporaryDirectory(prefix="worker-", dir=tmp) as worker:
                                row.update(evaluate_isolated(Path(workspace), spec, Path(worker)))
                            row["phase"] = "finished"
                            row["status"] = ("incomplete" if row.get("error") else
                                             "passed" if row["checks"] and all(c["outcome"] in {"passed", "limited", "unsupported"}
                                                                  for c in row["checks"]) else "failed")
                            row["passed"] = row["status"] == "passed"
                            row["limited_checks"] = [c["name"] for c in row["checks"] if c["outcome"] == "limited"]
                        except Exception as exc:
                            row.update(passed=False, status="incomplete", error=f"{type(exc).__name__}: {exc}")
                            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                                detail = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
                                row["stderr_tail"] = detail[-2000:]
                        # Preserve check outcomes even if workspace cleanup fails.
                        write_json(args.output, report)
                    row["cleanup_verified"] = not Path(workspace).exists()
                    report.update(summarize(report["repositories"], selected_ids))
                    write_json(args.output, report)
                    print(json.dumps({"repository": spec["id"], "status": row["status"]}), flush=True)
                report.update(summarize(report["repositories"], selected_ids))
    finally:
        if not args.ranking:
            report.update(summarize(report["repositories"], selected_ids))
        report["cleanup_verified"] = workspace_root is not None and not workspace_root.exists()
        if not report["cleanup_verified"]:
            report.update(status="incomplete", passed=False, complete=False, reason="cleanup_unverified")
        if json.loads(json.dumps(evidence_identity())) != identity:
            report.update(status="incomplete", passed=False, complete=False, reason="inputs_changed_during_run")
        write_json(args.output, report)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
