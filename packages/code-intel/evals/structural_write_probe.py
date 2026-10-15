"""Small persistence diagnostic; no cloud, model, corpus download or timing gate.

Run from the checkout with its Python environment. Temporary databases are
deleted; stdout contains identities and observations. The baseline commit must
already exist locally. Each CPU competitor stops after 20s; cases that outlast it
are explicitly marked as only partially contended.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import platform
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from attocode_intel._internal.integrations.context.index_store import IndexStore, StoredFile

BASELINE = "5851c7ca3cc9e54b8b7691d0decb0cbb518dfa85"
SOURCE = "packages/code-intel/src/attocode_intel/_internal/integrations/context/index_store.py"


def cpu_competitor(stop):
    deadline = time.monotonic() + 20
    while not stop.is_set() and time.monotonic() < deadline:
        sum(i * i for i in range(10000))


def probe():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:{SOURCE}"], timeout=10)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "IndexStore")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "save_analysis_batch")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<frozen baseline method>", "exec"), namespace)
    symbols = [dict(name=f"helper{i}", qualified_name=f"helper{i}", kind="function", line=i)
               for i in range(32)]
    refs = [dict(symbol_name=f"helper{i}", line=i, syntax_name=f"helper{i}",
                 caller_qualified_name="caller", definition_key=f"file:{i}") for i in range(32)]
    files = [(f"file{i}.py", symbols, refs) for i in range(40)]
    results = []
    with tempfile.TemporaryDirectory(prefix="quality-structural-") as directory:
        for contention in (False, True):
            for name, write in (("legacy", namespace[method.name]), ("batched", IndexStore.save_analysis_batch)):
                store = IndexStore(str(Path(directory) / f"{name}-{contention}.db"))
                stop = threading.Event()
                worker = threading.Thread(target=cpu_competitor, args=(stop,), daemon=True)
                try:
                    store.save_files_batch([StoredFile(p, 1, 1, "python", 1, "x") for p, _, _ in files])
                    if contention:
                        worker.start()
                    start = time.monotonic()
                    write(store, files)
                    elapsed = time.monotonic() - start
                    full_contention = worker.is_alive() if contention else None
                    stop.set()
                    if contention:
                        worker.join()
                    rows = [list(map(tuple, store._get_conn().execute(f"SELECT * FROM {table} ORDER BY id")))
                            for table in ("symbols", "refs")]
                    results.append(dict(method=name, cpu_thread=contention, seconds=elapsed,
                                        competitor_active_at_end=full_contention,
                                        rows=[len(r) for r in rows],
                                        row_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest()))
                finally:
                    stop.set()
                    if worker.ident is not None:
                        worker.join()
                    store.close()
    assert len({r["row_sha256"] for r in results}) == 1
    return dict(baseline_commit=BASELINE, baseline_source_sha256=hashlib.sha256(source).hexdigest(),
                candidate_source_sha256=hashlib.sha256(Path(inspect.getfile(IndexStore)).read_bytes()).hexdigest(),
                python=platform.python_version(), platform=platform.platform(),
                fixture={"files": 40, "symbols_per_file": 32, "references_per_file": 32},
                scope="One observation per case; synthetic CPU contention, not cloud latency or an agent study",
                results=results, cleanup_verified=True)


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
