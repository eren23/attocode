"""Bounded lexical SQL diagnostic; synthetic contention, no cloud or model calls.

Baseline must already exist locally. Disposable databases are removed; each
competitor stops after 20 seconds. One observation per case is not a timing gate.
"""

import ast
import hashlib
import inspect
import json
import platform
import subprocess
import tempfile
import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from attocode_intel._internal.integrations.context import semantic_search as search

BASELINE = "4f33254130fb2817c44cfa7a57e3e213822b9560"
SOURCE = "packages/code-intel/src/attocode_intel/_internal/integrations/context/semantic_search.py"
source = subprocess.check_output(["git", "show", f"{BASELINE}:{SOURCE}"], timeout=10)
cls = next(
    n
    for n in ast.parse(source).body
    if isinstance(n, ast.ClassDef) and n.name == "SemanticSearchManager"
)
scope = dict(vars(search))
for name in ("_save_kw_cache", "_sync_body_index"):
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "<frozen baseline method>", "exec"),
        scope,
    )
legacy_cache, legacy_body = scope["_save_kw_cache"], scope["_sync_body_index"]


def cpu(stop):
    end = time.monotonic() + 20
    while not stop.is_set() and time.monotonic() < end:
        sum(i * i for i in range(10000))


def measure(fn, contended):
    stop = threading.Event()
    worker = threading.Thread(target=cpu, args=(stop,))
    if contended:
        worker.start()
    started = time.monotonic()
    try:
        fn()
        elapsed = time.monotonic() - started
        full = worker.is_alive() if contended else None
    finally:
        stop.set()
        if contended:
            worker.join()
    return elapsed, full


results = []
with tempfile.TemporaryDirectory(prefix="quality-lexical-sql-") as scratch:
    for task in ["keyword", "body_delete"]:
        for contended in [False, True]:
            for arm in ["legacy", "batched"]:
                root = Path(scratch) / f"{task}-{contended}-{arm}"
                root.mkdir()
                mgr = search.SemanticSearchManager(str(root))
                try:
                    if task == "keyword":
                        documents = [
                            search._KeywordDoc(
                                f"func:{i}",
                                f"f{i % 256}.py",
                                "function",
                                f"helper{i}",
                                "preview",
                                False,
                                False,
                                {"needle": 2},
                                2,
                            )
                            for i in range(2048)
                        ]
                        mtimes = {f"f{i}.py": 1.0 for i in range(256)}
                        method = (
                            legacy_cache
                            if arm == "legacy"
                            else search.SemanticSearchManager._save_kw_cache
                        )
                        elapsed, full = measure(partial(method, mgr, documents, mtimes), contended)
                        conn = mgr._open_kw_cache_db()
                        rows = [
                            conn.execute(f"SELECT rowid,* FROM {t} ORDER BY rowid").fetchall()
                            for t in ["kw_files", "kw_docs"]
                        ]
                    else:
                        paths = [root / f"f{i:03}.py" for i in range(133)]
                        for p in paths:
                            p.write_text("def helper(): return 1\n")

                        def ctx(ps):
                            return SimpleNamespace(
                                _ensure_fresh=lambda: None,
                                _files=[
                                    SimpleNamespace(path=str(p), relative_path=p.name) for p in ps
                                ],
                            )

                        mgr._sync_body_index(ctx(paths))
                        assert mgr._body_index_built
                        mgr._body_index_built = False
                        method = (
                            legacy_body
                            if arm == "legacy"
                            else search.SemanticSearchManager._sync_body_index
                        )
                        elapsed, full = measure(partial(method, mgr, ctx(paths[-1:])), contended)
                        assert mgr._body_index_built
                        conn = mgr._open_body_db()
                        rows = [
                            conn.execute(f"SELECT rowid,* FROM {t} ORDER BY rowid").fetchall()
                            for t in ["body_fts", "body_file_fts"]
                        ]
                        rows.append(
                            conn.execute(
                                "SELECT file_path,size FROM body_files ORDER BY file_path"
                            ).fetchall()
                        )
                    conn.close()
                    results.append(
                        dict(
                            task=task,
                            arm=arm,
                            cpu_thread=contended,
                            seconds=elapsed,
                            competitor_active_at_end=full,
                            row_counts=[len(r) for r in rows],
                            row_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                        )
                    )
                finally:
                    mgr.close()
for task in ["keyword", "body_delete"]:
    assert len({r["row_sha256"] for r in results if r["task"] == task}) == 1
print(
    json.dumps(
        dict(
            baseline_commit=BASELINE,
            baseline_source_sha256=hashlib.sha256(source).hexdigest(),
            candidate_source_sha256=hashlib.sha256(
                Path(inspect.getfile(search)).read_bytes()
            ).hexdigest(),
            probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            python=platform.python_version(),
            platform=platform.platform(),
            fixture={
                "keyword_docs": 2048,
                "keyword_files": 256,
                "body_files": 133,
                "body_files_deleted": 132,
            },
            scope="Single observations, synthetic CPU contention; not cloud latency or release evidence",
            results=results,
            cleanup_verified=True,
        ),
        indent=2,
    )
)
