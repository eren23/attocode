"""Supervised cold-index mechanism probe; never a release gate or cloud provisioner.

Default: two tiny synthetic runs. --pack requires explicit worker-only downloads.
Fresh processes and source copies for concurrent and prehydrated arms. No models.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

import yaml
from attocode_intel.gateway import OperationGateway
from attocode_intel.request_context import bind_request
from filelock import FileLock

from eval.quality.corpus import PACK, evidence_identity, materialize, ready_search
from eval.quality.runner import GIB, REPO, environment, managed_root, supervise, write_json


class ProbeGateway(OperationGateway):
    def __init__(self, root, mode):
        super().__init__(str(root), "daily", watch=False)
        self.mode = mode
        self.probe_service = None
        self.prepared = False
        self.prehydration_seconds = 0.0
        self.prehydration_error = None

    def _warm_search(self, context):
        with bind_request(context):
            self.probe_service = context.service
            if self.prehydration_error:
                return
            if self.mode == "prehydrated" and not self.prepared:
                start = time.monotonic()
                try:
                    ast = context.service._get_ast_service()
                    if ast._hydration_thread:
                        ast._hydration_thread.join(timeout=240)
                        if ast._hydration_thread.is_alive():
                            raise TimeoutError("Prehydration exceeded 240 seconds")
                    if ast.hydration_snapshot().get("phase") != "ready":
                        raise RuntimeError("Structural hydration did not finish")
                    self.prepared = True
                except Exception as exc:
                    self.prehydration_error = str(exc)[:500]
                    return
                finally:
                    self.prehydration_seconds += time.monotonic() - start
            if not self.prehydration_error:
                super()._warm_search(context)

    def snapshot(self):
        service = self.probe_service
        manager = service._semantic_search if service else None
        ast = service._ast_service if service else None
        return {
            "prehydration_seconds": self.prehydration_seconds,
            "prehydration_error": self.prehydration_error,
            "index": manager.candidate_diagnostics() if manager else None,
            "profile": manager.index_probe.snapshot() if manager and manager.index_probe else None,
            "structural": ast.hydration_snapshot() if ast else None,
        }


def source_identity(root):
    digest = hashlib.sha256()
    files = total = 0
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            digest.update(str(p.relative_to(root)).encode() + b"\0" + data)
            files += 1
            total += len(data)
    return {"sha256": digest.hexdigest(), "files": files, "bytes": total}


async def observe(root, spec, mode, output, record):
    gateway = ProbeGateway(root, mode)
    stop = threading.Event()
    lock = threading.Lock()
    started = time.monotonic()

    def checkpoint():
        with lock:
            write_json(
                output,
                {**record, "elapsed_seconds": time.monotonic() - started, **gateway.snapshot()},
            )

    def monitor():
        while not stop.wait(0.5):
            checkpoint()

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    try:
        content = (root / spec["file"]).read_text()
        assert spec["anchor"] in content
        if spec.get("source_sha256"):
            assert hashlib.sha256(content.encode()).hexdigest() == spec["source_sha256"]
        response = await gateway.execute_mcp(
            "search_symbols", {"name": spec["symbol"], "max_tokens": 4000}
        )
        assert not response.isError
        definitions = json.loads(response.content[0].text)["data"]
        choices = [
            r for r in definitions if r["file_path"] == spec["file"] and r["name"] == spec["symbol"]
        ]
        assert len(choices) == 1, "Pinned definition missing or ambiguous"
        response = await gateway.execute_mcp(
            "inspect_symbol",
            {
                "symbol_name": spec["symbol"],
                "file_path": spec["file"],
                "line": choices[0]["start_line"],
                "max_tokens": 4000,
            },
        )
        assert not response.isError
        if gateway.prehydration_error:
            raise RuntimeError(gateway.prehydration_error)
        response, warmup = await ready_search(
            gateway,
            {
                "query": spec.get("query", spec["symbol"]),
                "file_filter": spec["file"],
                "top_k": 5,
                "max_tokens": 4000,
            },
        )
        data = json.loads(response.content[0].text)["data"]
        assert (
            not response.isError
            and data.get("results")
            and data["ranking"]["index"]["status"] == "ready"
        )
        record.update(
            status="completed",
            warmup=warmup,
            result_files=[r["file_path"] for r in data["results"]],
        )
    except Exception as exc:
        record.update(
            status="incomplete", error={"type": type(exc).__name__, "message": str(exc)[:4000]}
        )
    finally:
        # Last pre-close snapshot describes the measured attempt, not shutdown.
        stop.set()
        monitor_thread.join(timeout=2)
        checkpoint()
        await gateway.close()
    return record["status"] == "completed"


def worker(work, mode, pack, output):
    assert (work / ".index-probe-owned").read_text() == "index-probe-v1"
    root = work / mode
    root.mkdir()
    if pack and (sys.platform != "linux" or os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1"):
        raise ValueError("Pinned corpus diagnostics require an explicit Linux worker")
    if pack:
        spec = next(r for r in yaml.safe_load(PACK.read_text())["repositories"] if r["id"] == pack)
        materialize(spec, root, work / "cache")
    else:
        for i in range(24):
            (root / f"file{i}.py").write_text(
                f"def probe_helper{i}(value):\n    return value + 1\n"
            )
        spec = {
            "id": "synthetic",
            "file": "file0.py",
            "symbol": "probe_helper0",
            "anchor": "def probe_helper0(",
        }
    record = {
        "mode": mode,
        "identity": evidence_identity(),
        "probe_enabled": os.environ.get("ATTOCODE_INTEL_INDEX_PROBE") == "1",
        "pack": spec["id"],
        "revision": spec.get("commit"),
        "source": source_identity(root),
        "status": "running",
        "scope": "Instrumented mechanism diagnostic, not full quality gate or performance claim",
    }
    write_json(output, record)
    return asyncio.run(observe(root, spec, mode, output, record))


def run(root, pack=None, seconds=600):
    if not 1 <= seconds <= 600:
        raise ValueError("Probe budget must be 1..600 seconds")
    if pack and (sys.platform != "linux" or os.environ.get("QUALITY_ALLOW_DOWNLOADS") != "1"):
        raise ValueError(
            "Pinned corpus diagnostics require an explicit Linux worker; use synthetic locally"
        )
    if pack and pack not in {r["id"] for r in yaml.safe_load(PACK.read_text())["repositories"]}:
        raise ValueError("Unknown pinned pack")
    root = managed_root(root)
    with FileLock(str(root / ".lock"), timeout=0):
        name = "index-probe-" + uuid.uuid4().hex[:12]
        directory, work = root / "runs" / name, root / "work" / name
        directory.mkdir()
        work.mkdir()
        (work / ".index-probe-owned").write_text("index-probe-v1")
        env = environment(root)
        # Diagnostics cannot inherit a configured model/reranker or remote endpoint.
        for key in list(env):
            if key.startswith(("ATTOCODE_", "SYSTEMONE_")):
                env.pop(key)
        env.update(
            ATTOCODE_INTEL_INDEX_PROBE="1",
            ATTOCODE_INTEL_RANKING_PROVIDER="off",
            ATTOCODE_INTEL_PRECISION="off",
            ATTOCODE_NL_EMBEDDING_MODE="none",
            ATTOCODE_LOCAL_ONLY="1",
            PYTHONPATH=str(REPO / "packages/code-intel/src") + os.pathsep + str(REPO),
            TMPDIR=str(work),
            TMP=str(work),
            TEMP=str(work),
        )
        identity = evidence_identity()
        report = {
            "identity": identity,
            "pack": pack or "synthetic",
            "arms": [],
            "model_runs": 0,
            "release_gate": False,
            "status": "running",
            "budget_seconds": seconds,
        }
        deadline, wall_deadline = time.monotonic() + seconds, time.time() + seconds
        try:
            for mode in ("concurrent", "prehydrated"):
                command = [
                    sys.executable,
                    "-m",
                    "eval.quality.index_probe",
                    "--worker",
                    str(work),
                    "--mode",
                    mode,
                    "--output",
                    str(directory / (mode + ".json")),
                ]
                if pack:
                    command += ["--pack", pack]
                row = supervise(
                    command,
                    cwd=REPO,
                    env=env,
                    root=root,
                    log=directory / (mode + ".log"),
                    deadline=deadline,
                    wall_deadline=wall_deadline,
                    max_bytes=5 * GIB,
                )
                report["arms"].append({"mode": mode, **row})
                write_json(directory / "report.json", report)
                if row.get("reason") or not row.get("cleanup_verified"):
                    break
        finally:
            shutil.rmtree(work)
            report["cleanup_verified"] = not work.exists() and all(
                r.get("cleanup_verified") for r in report["arms"]
            )
            report["inputs_unchanged"] = evidence_identity() == identity
            report["status"] = (
                "completed"
                if len(report["arms"]) == 2 and all(r["status"] == "passed" for r in report["arms"])
                else "incomplete"
            )
            if not report["cleanup_verified"] or not report["inputs_unchanged"]:
                report["status"] = "incomplete"
            paths = [directory / (mode + ".json") for mode in ("concurrent", "prehydrated")]
            records = [json.loads(p.read_text()) for p in paths if p.exists()]
            report["same_source"] = (
                len(records) == 2 and records[0]["source"] == records[1]["source"]
            )
            report["worker_inputs_match"] = len(records) == 2 and all(
                all(
                    r.get("identity", {}).get(k) == identity[k]
                    for k in ("source_sha256", "harness_sha256", "fixture_sha256", "pack_sha256")
                )
                for r in records
            )
            if not report["same_source"] or not report["worker_inputs_match"]:
                report["status"] = "incomplete"
            write_json(directory / "report.json", report)
        return directory, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / ".attocode/quality")
    parser.add_argument("--pack")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["concurrent", "prehydrated"], help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not args.mode or not args.output:
            parser.error("Worker requires mode/output")
        return 0 if worker(args.worker, args.mode, args.pack, args.output) else 1
    directory, report = run(args.root, args.pack, args.seconds)
    print(json.dumps({"directory": str(directory), "status": report["status"]}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
