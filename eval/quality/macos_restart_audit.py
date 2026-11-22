"""Witness first content searches through the released stdio CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from importlib.metadata import version
from pathlib import Path

FILES = ("trigrams.db", "trigrams.lookup", "trigrams.postings")
OLD = "amberfreshneedle"
NEW = {"unchanged": OLD, "edit": "jadefreshneedle", "branch": "cobaltfreshneedle"}
STABLE = "stablefreshneedle"
TOOLS = ("fast_search", "semantic_search")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source(token):
    return f'def fixture_probe():\n    return "{token}"\n'


def snapshot(root):
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "branch": git(root, "branch", "--show-current"),
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))},
    }


def prepare(root):
    root.mkdir()
    git(root, "init", "-b", "audit-a")
    git(root, "config", "user.name", "Synthetic restart fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / ".gitignore").write_text(".attocode/\n")
    (root / "target.py").write_text(source(OLD))
    (root / "control.py").write_text(source(STABLE))
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    git(root, "switch", "-c", "audit-b")
    (root / "target.py").write_text(source(NEW["branch"]))
    git(root, "add", "target.py")
    git(root, "commit", "-m", "change content on branch")
    git(root, "switch", "audit-a")


def index_hashes(root):
    index = root / ".attocode" / "index"
    return {name: hashlib.sha256((index / name).read_bytes()).hexdigest()
            for name in FILES if (index / name).is_file()}


async def session(root, calls, record, output, label):
    log = output / f"{label}.stderr"
    with log.open("wb") as stderr:
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "attocode_intel.entrypoint",
            "--project", str(root), "--profile", "full", "--no-watch",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=stderr, limit=2**20,
        )
        record.update(pid=child.pid, root=str(root), messages=[], calls=[], stderr=log.name)
        request_id = 0

        async def send(message):
            wire = {"jsonrpc": "2.0", **message}
            record["messages"].append({"sent": wire})
            child.stdin.write(json.dumps(wire).encode() + b"\n")
            await child.stdin.drain()

        async def request(method, params):
            nonlocal request_id
            request_id += 1
            await send({"id": request_id, "method": method, "params": params})
            async with asyncio.timeout(25):
                while True:
                    raw = await child.stdout.readline()
                    if not raw:
                        raise RuntimeError(f"EOF before {method} response")
                    reply = json.loads(raw)
                    record["messages"].append({"received": reply})
                    if reply.get("id") == request_id:
                        assert "error" not in reply, reply
                        return reply["result"]
                    assert "id" not in reply, reply

        try:
            hello = await request("initialize", {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "synthetic-restart-audit", "version": "1"},
            })
            assert hello["serverInfo"]["name"] == "attocode-code-intel"
            assert hello["serverInfo"]["version"] == "0.1.39"
            await send({"method": "notifications/initialized"})
            for tool, query, expected in calls:
                arguments = {"pattern": query, "explain": True} if tool == "fast_search" else {
                    "query": query, "mode": "keyword", "top_k": 5, "max_tokens": 4000,
                }
                reply = await request("tools/call", {"name": tool, "arguments": arguments})
                assert not reply.get("isError"), reply
                if tool == "fast_search":
                    raw_text = reply["content"][0]["text"]
                    hits = re.findall(r"(?m)^([\w./-]+\.py):\d+:(.*)$", raw_text)
                    assert all(query in line for _, line in hits)
                    paths = sorted({path for path, _ in hits})
                    ready = "--- Search Diagnostics ---" in raw_text and "index-build-failed" not in raw_text
                else:
                    payload = reply["structuredContent"]
                    assert not payload["metadata"]["truncated"]
                    assert payload["metadata"]["source"] == "local"
                    ready = payload["data"]["ranking"]["index"]["status"] == "ready"
                    paths = sorted({hit["file_path"] for hit in payload["data"]["results"]})
                record["calls"].append({
                    "request_id": request_id, "tool": tool, "query": query,
                    "expected": expected, "actual": paths, "ready": ready,
                    "passed": ready and paths == expected,
                })
        finally:
            child.stdin.close()
            try:
                await asyncio.wait_for(child.wait(), timeout=10)
                record["forced_exit"] = False
            except TimeoutError:
                child.kill()
                await child.wait()
                record["forced_exit"] = True
            record["exit_code"] = child.returncode
        assert not record["forced_exit"] and record["exit_code"] == 0, record


async def case(directory, tool, mutation, record, output):
    label = f"{tool}-{mutation}"
    root = directory / label
    prepare(root)
    before = snapshot(root)
    record["source_before"] = before
    await session(root, [("fast_search", OLD, ["target.py"]), (tool, OLD, ["target.py"])],
                  record.setdefault("warm", {}), output, f"{label}-warm")
    assert all(row["passed"] for row in record["warm"]["calls"])
    saved = index_hashes(root)
    assert set(saved) == set(FILES)
    assert not list((root / ".attocode" / "index").glob("trigrams.db-*"))
    record["saved"] = saved
    prior_cache = directory / f"{label}-pre-reopen-cache"
    shutil.copytree(root / ".attocode", prior_cache)
    if mutation == "edit":
        (root / "target.py").write_text(source(NEW[mutation]))
    elif mutation == "branch":
        git(root, "switch", "audit-b")
    after = snapshot(root)
    assert (after["head"] != before["head"]) == (mutation == "branch")
    assert (after["files"] != before["files"]) == (mutation != "unchanged")
    record.update(source_after=after, saved_after_mutation=index_hashes(root))
    assert record["saved_after_mutation"] == saved

    first_query = NEW[mutation]
    absent = OLD if mutation != "unchanged" else NEW["edit"]
    calls = [(tool, first_query, ["target.py"]), (tool, absent, []),
             (tool, STABLE, ["control.py"])]
    clean = directory / f"{label}-clean"
    shutil.copytree(root, clean, ignore=shutil.ignore_patterns(".attocode"))
    assert not index_hashes(clean) and snapshot(clean) == after
    record["clean_source"] = snapshot(clean)
    await session(clean, calls, record.setdefault("clean", {}), output, f"{label}-clean")
    assert all(row["passed"] for row in record["clean"]["calls"])
    await session(root, calls, record.setdefault("reopen", {}), output, f"{label}-reopen")
    assert snapshot(root) == after
    record["after_reopen"] = index_hashes(root)
    reopen = record["reopen"]["calls"]
    record["qualified"] = all(row["ready"] for row in reopen) and reopen[-1]["passed"]
    record["passed"] = record["qualified"] and all(row["passed"] for row in reopen)
    if mutation != "unchanged" and record["qualified"] and not reopen[0]["passed"]:
        shutil.rmtree(root / ".attocode")
        shutil.copytree(prior_cache, root / ".attocode")
        assert index_hashes(root) == saved and snapshot(root) == after
        for name in FILES:
            (root / ".attocode" / "index" / name).unlink()
        assert not index_hashes(root)
        await session(root, calls, record.setdefault("without_saved_trigrams", {}),
                      output, f"{label}-without-saved-trigrams")
        record["isolated_saved_trigram_cause"] = all(
            row["passed"] for row in record["without_saved_trigrams"]["calls"]
        )


async def main(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "wheel_version": version("attocode-code-intel"),
        "product_head": git(Path.cwd(), "rev-parse", "HEAD^"),
        "diagnostic_head": git(Path.cwd(), "rev-parse", "HEAD"),
        "cases": [],
        "harness_errors": [],
    }
    assert report["wheel_version"] == "0.1.39"
    with tempfile.TemporaryDirectory(prefix="attocode-restart-") as name:
        directory = Path(name).resolve()
        for tool in TOOLS:
            for mutation in NEW:
                record = {"tool": tool, "mutation": mutation}
                report["cases"].append(record)
                try:
                    await case(directory, tool, mutation, record, output)
                except Exception:
                    report["harness_errors"].append({
                        "tool": tool, "mutation": mutation, "traceback": traceback.format_exc(),
                    })
    report["owned_fixture_removed"] = not directory.exists()
    report["tracked_source_unchanged"] = not git(Path.cwd(), "diff", "HEAD", "--")
    controls = [row for row in report["cases"] if row["mutation"] == "unchanged"]
    qualified = (not report["harness_errors"] and report["owned_fixture_removed"]
                 and report["tracked_source_unchanged"] and len(controls) == 2
                 and all(row.get("passed") for row in controls)
                 and all(row.get("qualified") for row in report["cases"]))
    report["verdict"] = ("incomplete" if not qualified else
                         "passed" if all(row["passed"] for row in report["cases"])
                         else "qualified-product-failure")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["verdict"], flush=True)
    return 0 if report["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]))))
