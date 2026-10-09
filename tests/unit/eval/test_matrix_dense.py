import json
import subprocess
from dataclasses import asdict

import numpy as np
import pytest

from eval.matrix import arms, dense
from eval.matrix import run as matrix
from eval.matrix.datasets import Instance

FILES = {"pkg/config.py": "def load_config(path):\n    return path\n", "pkg/parse.py": "def parse(text):\n    return text\n",
         "README.md": "Read the settings.\n"}


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(root, files):
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text if isinstance(text, bytes) else text.encode())
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "c")
    return _git(root, "rev-parse", "HEAD")


def test_windows_follow_the_dense_pool_rule(tmp_path):
    text = "".join(f"line {n}\n" for n in range(100)).encode()
    found = dense.windows("a/b.py", text)
    assert len(found) == 3 and found[0].startswith("File: a/b.py\nline 0\nline 1\n") and found[2].endswith("line 99")
    assert dense.windows("x.bin", b"\0\1") == [] and dense.windows("empty.py", b"") == ["File: empty.py\n"]
    assert len(dense.windows("long.py", b"x" * 100 + b"\n")[0]) == len("File: long.py\n") + 100
    assert len(dense.windows("wide.py", (b"x" * 100 + b"\n") * 40)[0]) == dense.MAX_CHARS
    assert len(dense.windows("big.py", b"a\n" * 2000)) == dense.MAX_WINDOWS
    (tmp_path / "f").write_bytes(text)
    assert dense.git_oid(text) == _git(tmp_path, "hash-object", "f")


def test_store_parts_are_content_addressed(tmp_path):
    store = dense.Store(tmp_path / "emb")
    vectors = np.arange(12, dtype=np.float32).reshape(3, 4)
    part = store.add(["a", "b"], [2, 1], vectors)
    assert store.add(["a", "b"], [2, 1], vectors) == part  # the same index gives the same part
    fresh = dense.Store(tmp_path / "emb")
    assert fresh.get("b").tolist() == [[8, 9, 10, 11]] and fresh.get("a").shape == (2, 4) and fresh.get("c") is None
    assert fresh.get("a").dtype == np.float16
    with pytest.raises(ValueError, match="2 rows"):
        store.add(["c"], [2], vectors)


def test_import_checks_the_trees_and_moves_the_parts(tmp_path, capsys):
    sha = _repo(tmp_path / "bench" / "k", FILES)
    cache, work = tmp_path / "cache", tmp_path / "work"
    matrix.snapshot(cache, [Instance(id="pack/k::a", repo="k", base_commit=sha, language="", category="",
                                     created_at="", queries={}, gold=[], grades=None)], sources=(tmp_path / "bench",))
    tree = json.loads(matrix._tree_file(cache, "k", sha).read_text())
    pod = {"key": "k", "repo": "o/k", "commit": sha, "tree": tree["tree"], "error": None, "stored": dense.digest(tree)}
    snapshots = [pod, {**pod, "stored": "other"}, {**pod, "commit": "0" * 40, "tree": None, "error": "git fetch: x"}]
    (work / "emb" / dense.TAG).mkdir(parents=True)
    (work / "manifest.json").write_text(json.dumps({"tag": dense.TAG, "snapshots": snapshots}))
    part = dense.Store(work / "emb" / dense.TAG).add(["a"], [1], np.ones((1, 2), np.float32))
    dense.import_(work, cache)
    out = capsys.readouterr().out
    assert "trees: 1 equal to the local trees, 2 not" in out and "added 1 parts" in out
    assert (work / "emb" / dense.TAG / f"{part}.npy").samefile(cache / "emb" / dense.TAG / f"{part}.npy")
    assert dense.Store(cache / "emb" / dense.TAG).get("a").tolist() == [[1, 1]]
    dense.import_(work, cache)  # again after the next copy from the pod: nothing new
    assert "added 0 parts" in capsys.readouterr().out


def test_a_file_scores_its_best_window(tmp_path):
    for path, data in {"a.py": b"def a(): pass\n", "b.py": b"def b(): pass\n", "img.bin": b"\0png"}.items():
        (tmp_path / path).write_bytes(data)
    store = dense.Store(tmp_path / "emb")
    keys = [dense.file_key(p, dense.git_oid((tmp_path / p).read_bytes())) for p in ("a.py", "b.py")]
    store.add(keys, [2, 1], np.array([[0, 1, 0], [1, 0, 0], [0.8, 0.6, 0]], np.float32))  # a.py has two windows
    names, starts, vectors = dense.vectors(store, tmp_path, ["a.py", "b.py", "img.bin"])
    assert names == ["a.py", "b.py"] and starts.tolist() == [0, 2]  # a binary file has no windows
    assert dense.rank(names, starts, vectors, np.array([1, 0, 0]), 10) == ["a.py", "b.py"]  # 1.0 (2nd window), 0.8
    assert dense.rank(names, starts, vectors, np.array([0.6, 0.8, 0]), 10) == ["b.py", "a.py"]  # 0.96, 0.8
    assert dense.rank(names, starts, vectors, np.array([0, 0, 1]), 1) == ["a.py"]  # a tie goes by path
    (tmp_path / "c.py").write_text("new\n")
    with pytest.raises(dense.MissingVectorsError, match="c.py"):
        dense.vectors(store, tmp_path, ["a.py", "c.py"])


def test_rrf_cell_fuses_the_first_48_files_of_each_part():
    product, found = [f"p{i}" for i in range(60)], ["d0", "p1", "p0"]
    fused = arms.rrf([product, found])
    assert fused[:4] == ["p0", "p1", "d0", "p2"] and len(fused) == 49 and "p48" not in fused
    ok, dense_ok = {"status": "ok", "lists": {"fused": product}, "ms": 2.0}, {"status": "ok", "lists": {"files": found}, "ms": 1.0}
    key, result = arms.fuse("rrf(product+dense)", [("k1", ok), ("k2", dense_ok)])
    assert result == {"status": "ok", "lists": {"rrf": fused}, "page": None, "ms": 3.0}
    assert arms.fuse("rrf(product+dense)", [("k1", ok), ("k2", None)]) == (key, None)
    failed = {"status": "index_failed", "error": "x", "lists": {"fused": []}, "page": None, "ms": None}
    assert arms.fuse("rrf(product+dense)", [("k1", failed), ("k2", dense_ok)])[1] == {**failed, "lists": {}}
    assert arms.fuse("rrf(product+dense)", [("k1", ok), ("k3", dense_ok)])[0] != key
    assert arms.families(["rrf(product+dense)", "kw"]) == ["dense", "product"]


def test_dense_cells_through_the_stages(tmp_path, monkeypatch, capsys):
    product_repo = tmp_path / "product"
    _repo(product_repo, {"packages/code-intel/src/x.py": "x = 1\n"})
    sha = _repo(tmp_path / "bench" / "k", {**FILES, "logo.png": b"\0png"})
    inst = Instance(id="pack/k::config", repo="k", base_commit=sha, language="", category="", created_at="",
                    queries={"full": "where is the config loaded", "title": "config"}, gold=["pkg/config.py"],
                    grades=None)
    out, cache = tmp_path / "out", tmp_path / "cache"
    out.mkdir()
    (out / "instances.jsonl").write_text(json.dumps(asdict(inst)) + "\n")
    matrix.snapshot(cache, [inst], sources=(tmp_path / "bench",))
    real = arms.run
    monkeypatch.setattr(arms, "run", lambda family, snap, query: {"lists": {"fused": ["README.md", "pkg/parse.py"]},
                                                                 "page": 2, "ms": 1.0} if family == "product"
                        else real(family, snap, query))
    cells = ["dense", "rrf(product+dense)"]

    matrix.retrieve(cache, [inst], cells, repo=product_repo)  # no vectors yet: nothing saved for dense
    assert capsys.readouterr().out.endswith("retrieve: 2 results made, 0 from the cache, 2 not ready\n")

    tree = json.loads(matrix._tree_file(cache, "k", sha).read_text())
    store = dense.store(cache)
    rows = {"pkg/config.py": [1, 0], "pkg/parse.py": [0, 1], "README.md": [0.6, 0.8]}
    keys = [dense.file_key(path, oid) for path, _mode, oid, _size in tree["entries"] if path in rows]
    store.add(keys, [1] * 3, np.array([rows[path] for path, *_ in tree["entries"] if path in rows], np.float32))
    store.add([dense.query_key(q) for q in inst.queries.values()], [1, 1], np.array([[1, 0], [0.9, 0.1]], np.float32))
    matrix.retrieve(cache, [inst], cells, repo=product_repo)
    assert capsys.readouterr().out.endswith("retrieve: 2 results made, 2 from the cache\n")
    matrix.retrieve(cache, [inst], cells, repo=product_repo)  # a second run needs no vectors and no model
    assert capsys.readouterr().out.endswith("retrieve: 0 results made, 4 from the cache\n")

    matrix.write_rows(out, cache, [inst], cells)
    got = {(r["variant"], r["cell"]): r for r in map(json.loads, (out / "results.jsonl").read_text().splitlines())}
    assert got["full", "dense"]["files"] == ["pkg/config.py", "README.md", "pkg/parse.py"]  # no png
    # README.md: 1/61 + 1/62, pkg/parse.py: 1/62 + 1/63, pkg/config.py: 1/61 (dense only)
    assert got["full", "rrf(product+dense)"]["files"] == ["README.md", "pkg/parse.py", "pkg/config.py"]
    assert {r["status"] for r in got.values()} == {"ok"} and len(got) == 4
