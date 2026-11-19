"""One synthetic correctness audit; run only in Actions, never against a user workspace."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from attocode_intel.freshness import WorkspaceWatcher
from attocode_intel.gateway import OperationGateway

TOKENS = {"initial": "amberfreshneedle", "edited": "jadefreshneedle", "branch": "cobaltfreshneedle"}
SYMBOLS = {stage: f"{stage}_probe" for stage in TOKENS}
PATHS = {"watched.py", "moved.py"}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source(stage):
    return f'def {SYMBOLS[stage]}():\n    return "{TOKENS[stage]}"\n'


def snapshot(root):
    return {"head": git(root, "rev-parse", "HEAD"), "branch": git(root, "branch", "--show-current"),
            "files": {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                "text": p.read_text()} for p in sorted(root.glob("*.py"))}}


def tracker_state(gateway):
    stores = next(iter(gateway._stores.values()), {})
    tracker = stores.get("freshness")
    return {"generation": tracker.generation if tracker else None,
            "manifest": dict(tracker.manifest or {}) if tracker else {}}


class Observer:
    """Delegate actual events and callback exactly once; only add observations."""
    def __init__(self, roots):
        self.roots = {str(root) for root in roots}
        self.rows = []
        self.lock = threading.Lock()
        self.local = threading.local()
        self.gateways = {}

    @contextmanager
    def installed(self):
        import watchfiles
        original_watch, original_init = watchfiles.watch, WorkspaceWatcher.__init__
        observer = self

        def watch(*args, **kwargs):
            root = str(args[0])
            for changes in original_watch(*args, **kwargs):
                if root in observer.roots:
                    row = {"root": root, "events": sorted((int(kind), str(path)) for kind, path in changes),
                           "delivered_at": time.monotonic(), "callback_called": False, "done": False}
                    with observer.lock:
                        observer.rows.append(row)
                    observer.local.row = row
                yield changes

        def init(instance, root, callback, debounce=500):
            if str(root) not in observer.roots:
                return original_init(instance, root, callback, debounce)

            def observed_callback():
                row = observer.local.row
                with observer.lock:
                    row["callback_called"] = True
                future = callback()

                def completed(result):
                    try:
                        error = result.exception()
                        state = tracker_state(observer.gateways[str(root)])
                        with observer.lock:
                            row.update(done=True, error=repr(error) if error else None,
                                       completed_at=time.monotonic(), state=state)
                    except BaseException as exc:
                        with observer.lock:
                            row.update(done=True, observation_error=repr(exc))

                future.add_done_callback(completed)
                return future

            return original_init(instance, root, observed_callback, debounce)

        watchfiles.watch, WorkspaceWatcher.__init__ = watch, init
        try:
            yield self
        finally:
            watchfiles.watch, WorkspaceWatcher.__init__ = original_watch, original_init

    def copy_rows(self):
        with self.lock:
            return json.loads(json.dumps(self.rows))

    async def observed(self, root, paths, after, *, canary=False):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if canary:
                (root / ".audit-ready").write_text(str(time.monotonic()))
            rows = [row for row in self.copy_rows() if row["root"] == str(root)
                    and row["delivered_at"] >= after and row["done"]
                    and any(Path(path).name in paths for _, path in row["events"])]
            if rows:
                return rows
            await asyncio.sleep(0.15)
        return []


async def public(gateway, operation, arguments):
    response = await gateway.execute(operation, arguments)
    if response.isError:
        raise RuntimeError(f"{operation}: {response.model_dump(mode='json')}")
    return response


async def check_public(gateway, expected_stage, expected_path):
    rows = []
    for stage, token in TOKENS.items():
        expected = {expected_path} if stage == expected_stage else set()
        response = await public(gateway, "search_symbols", {"name": SYMBOLS[stage]})
        text = response.content[0].text
        actual = {path for path in PATHS if path in text}
        rows.append({"operation": "search_symbols", "query": SYMBOLS[stage], "raw": text,
                     "expected": sorted(expected), "actual": sorted(actual), "pass": actual == expected})
        response = await public(gateway, "fast_search", {"pattern": token, "explain": True})
        text = response.content[0].text
        actual = set(re.findall(r"(?m)^([\w./-]+\.py):\d+:", text)) & PATHS
        rows.append({"operation": "fast_search", "query": token, "raw": text,
                     "expected": sorted(expected), "actual": sorted(actual), "pass": actual == expected})
        response = await public(gateway, "semantic_search", {"query": token, "top_k": 5,
                                "mode": "keyword", "max_tokens": 4000})
        data = response.structuredContent
        assert not data["metadata"]["truncated"], data
        assert data["data"]["ranking"]["index"]["status"] == "ready", data
        actual = {row["file_path"] for row in data["data"]["results"]} & PATHS
        rows.append({"operation": "semantic_search", "query": token, "raw": data,
                     "expected": sorted(expected), "actual": sorted(actual), "pass": actual == expected})
    response = await public(gateway, "search_symbols", {"name": "stable_probe"})
    text = response.content[0].text
    rows.append({"operation": "stable_symbol_control", "raw": text, "pass": "control.py" in text})
    response = await public(gateway, "fast_search", {"pattern": "stablefreshneedle"})
    text = response.content[0].text
    rows.append({"operation": "stable_content_control", "raw": text,
                 "pass": bool(re.search(r"(?m)^control\.py:\d+:", text))})
    return rows


def prepare(root):
    root.mkdir()
    git(root, "init", "-b", "audit-a")
    git(root, "config", "user.name", "Freshness fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / ".gitignore").write_text(".attocode/\n.audit-ready\n")
    (root / "watched.py").write_text(source("initial"))
    (root / "control.py").write_text('def stable_probe():\n    return "stablefreshneedle"\n')
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    git(root, "switch", "-c", "audit-b")
    (root / "watched.py").write_text(source("branch"))
    git(root, "add", ".")
    git(root, "commit", "-m", "branch source")
    git(root, "switch", "audit-a")


async def audit_route(root, watch, observer, route):
    gateway = OperationGateway(str(root), "full", watch=watch)
    observer.gateways[str(root)] = gateway
    route.update(watch=watch, debounce=500, stages=[], qualified=False)
    watcher = None
    workers = []
    try:
        await public(gateway, "symbols", {"path": "watched.py"})
        baseline = await check_public(gateway, "initial", "watched.py")
        assert all(row["pass"] for row in baseline), baseline
        index = next(iter(gateway._stores.values()))["trigrams"]
        assert index.is_ready(), "baseline requires a real ready trigram index"
        route["baseline"] = {"source": snapshot(root), "public": baseline, "trigram_ready": True}
        if watch:
            watcher = next(iter(gateway._stores.values()))["watcher"]
            canary = await observer.observed(root, {".audit-ready"}, time.monotonic(), canary=True)
            assert canary and all(not row.get("error") and not row.get("observation_error") for row in canary), canary
            route["registration"] = canary
        route["qualified"] = True
        for mutation, expected_stage, expected_path in [
            ("edit", "edited", "watched.py"), ("rename", "edited", "moved.py"),
            ("delete", None, None), ("switch-b", "branch", "watched.py"), ("switch-a", None, None),
        ]:
            before = tracker_state(gateway)
            started = time.monotonic()
            if mutation == "edit":
                (root / "watched.py").write_text(source("edited"))
            elif mutation == "rename":
                (root / "watched.py").rename(root / "moved.py")
            elif mutation == "delete":
                (root / "moved.py").unlink()
            elif mutation == "switch-b":
                git(root, "add", "-A")
                git(root, "commit", "-m", "deleted on branch a")
                git(root, "switch", "audit-b")
            else:
                git(root, "switch", "audit-a")
            stage = {"mutation": mutation, "expected_stage": expected_stage, "expected_path": expected_path,
                     "source": snapshot(root), "before": before}
            route["stages"].append(stage)
            if watch:
                stage["watcher"] = await observer.observed(root, PATHS, started)
            stage["before_public"] = tracker_state(gateway)
            stage["public"] = await check_public(gateway, expected_stage, expected_path)
            stage["after_public"] = tracker_state(gateway)
    finally:
        workers = list(gateway._workers.values())
        await gateway.close()
        route["cleanup"] = {"gateway_closed": gateway._closed, "stores_empty": not gateway._stores,
                            "watcher_stopped": watcher is None or not watcher.thread.is_alive(),
                            "workers_stopped": all(not thread.is_alive() for worker in workers for thread in worker._threads)}


async def run(output):
    report = {"schema": 1, "scope": "synthetic-local-freshness", "routes": [], "harness_errors": []}
    output.mkdir(parents=True, exist_ok=False)
    repo = Path.cwd()
    report["source_head"] = git(repo, "rev-parse", "HEAD")
    report["source_tree"] = git(repo, "rev-parse", "HEAD^{tree}")
    report["operator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="freshness-audit-") as temp:
        roots = [Path(temp) / "watch", Path(temp) / "stat"]
        for root in roots:
            prepare(root)
        observer = Observer(roots)
        with observer.installed():
            for root, watch in zip(roots, (True, False), strict=True):
                route = {"root": str(root)}
                report["routes"].append(route)
                try:
                    await audit_route(root, watch, observer, route)
                except Exception:
                    report["harness_errors"].append({"root": str(root), "traceback": traceback.format_exc()})
        report["events"] = observer.copy_rows()
    report["fixtures_removed"] = all(not root.exists() for root in roots)
    report["tracked_source_unchanged"] = not git(repo, "diff", "HEAD", "--")
    report["qualified_failures"] = [
        {"watch": route.get("watch"), "mutation": stage["mutation"], "operation": row["operation"],
         "query": row.get("query"), "expected": row.get("expected"), "actual": row.get("actual")}
        for route in report["routes"] if route["qualified"] for stage in route["stages"]
        for row in stage.get("public", []) if not row["pass"]]
    report["complete"] = (not report["harness_errors"] and report["fixtures_removed"]
                          and report["tracked_source_unchanged"] and all(
                              all(route["cleanup"].values()) for route in report["routes"]))
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("complete", "qualified_failures", "harness_errors")}, indent=2))
    return 0 if report["complete"] and not report["qualified_failures"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args().output)))
