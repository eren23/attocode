import json
import os
import subprocess
import sys
from dataclasses import asdict

import pytest

from eval.matrix import arms
from eval.matrix import run as matrix
from eval.matrix.datasets import Instance

FILES = {
    "pkg/config.py": "import yaml\n\ndef load_config(path):\n    return parse_yaml(path)\n",
    "pkg/parse.py": "def parse_yaml(path):\n    return yaml.safe_load(open(path))\n",
    "pkg/cli.py": "from pkg.config import load_config\n\ndef main():\n    load_config('settings.yaml')\n",
    "README.md": "Use load_config to read the settings.\n",
    "logo.png": "not an image",
    "big.txt": "x" * 3000,
}


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(root, files=FILES):
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    os.symlink("pkg/config.py", root / "config_link.py")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "c")
    return _git(root, "rev-parse", "HEAD")


def _instance(repo, commit, *queries):
    return Instance(id=f"pack/{repo}::{queries[0]}", repo=repo, base_commit=commit, language="", category="",
                    created_at="", queries=dict(zip(("full", "title"), queries, strict=False)),
                    gold=["pkg/config.py"], grades=None)


def test_grep_terms():
    terms, tails = arms.grep_terms(
        "Crash in `load_config(path)`: KeyError from yaml.safe_load, see https://x.org/a.b and "
        'File "/usr/lib/site-packages/pkg/parse.py", line 3. Don\'t touch setup.py or ParseError.')
    assert terms == ["load_config(path)", "load_config", "KeyError", "yaml.safe_load", "safe_load", "ParseError"]
    assert tails == ["pkg/parse.py", "setup.py"]


def test_grep_ranks_rare_terms_first_and_named_paths_on_top(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    snap = arms.Snapshot(tmp_path, sorted(FILES))
    # parse_yaml is in 2 files and load_config in 3; the query names cli.py, so it comes first.
    assert snap.grep("load_config calls parse_yaml, see cli.py") == ["pkg/cli.py", "pkg/config.py", "pkg/parse.py",
                                                                     "README.md"]
    assert snap.grep("nothing code-like here") == []


def test_snapshot_from_a_local_clone_and_a_remote(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "MAX_BYTES", 1000)
    sha = _repo(tmp_path / "bench" / "k")
    cache = tmp_path / "cache"
    matrix.snapshot(cache, [_instance("k", sha, "q")], sources=(tmp_path / "bench",))
    local = json.loads((cache / "trees" / f"k@{sha}.json").read_text())
    assert local["source"] == str(tmp_path / "bench" / "k") and local["commit"] == sha
    stored = sorted(entry[0] for entry in local["entries"] if matrix._stored(entry))
    assert stored == ["README.md", "config_link.py", "pkg/cli.py", "pkg/config.py", "pkg/parse.py"]  # no png, no big file

    remote = tmp_path / "remotes" / "o" / "r.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(tmp_path / "bench" / "k"), str(remote)], check=True)
    _git(remote, "config", "uploadpack.allowFilter", "true")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    monkeypatch.setattr(matrix, "REMOTE", f"file://{tmp_path}/remotes/{{}}.git")
    matrix.snapshot(cache, [_instance("o/r", sha, "q"), _instance("o/r", "0" * 40, "q")], sources=())
    fetched = json.loads((cache / "trees" / f"o__r@{sha}.json").read_text())
    assert fetched["tree"] == local["tree"] and [e for e in fetched["entries"] if matrix._stored(e)] == \
        [e for e in local["entries"] if matrix._stored(e)]
    assert next(e[3] for e in fetched["entries"] if e[0] == "big.txt") == -1  # over the limit: not fetched
    assert "error" in json.loads((cache / "trees" / f"o__r@{'0' * 40}.json").read_text())
    fetches, real = [], matrix._remote
    monkeypatch.setattr(matrix, "_remote", lambda repo, tmp: fetches.append(repo) or real(repo, tmp))
    failed = [_instance("o/r", "0" * 40, "q")]
    matrix.snapshot(cache, failed, sources=())  # a failed snapshot is a result
    matrix.snapshot(cache, failed, sources=(), retry_failed=True)
    assert fetches == ["o/r"]

    root = tmp_path / "tree"
    assert sorted(matrix._materialize(cache, fetched, root)) == [p for p in stored if p != "config_link.py"]
    assert (root / "config_link.py").is_symlink() and not (root / "big.txt").exists()


def _workspace(tmp_path, monkeypatch, calls):
    """A product repository, a snapshot of a source repository, and a fake arm that counts its calls."""
    product = tmp_path / "product"
    _repo(product, {"packages/code-intel/src/x.py": "x = 1\n"})
    sha = _repo(tmp_path / "bench" / "k")
    out, cache = tmp_path / "out", tmp_path / "cache"
    instances = [_instance("k", sha, "load_config fails", "load_config"), _instance("k", sha, "parse_yaml")]
    out.mkdir()
    (out / "instances.jsonl").write_text("".join(json.dumps(asdict(inst)) + "\n" for inst in instances))
    matrix.snapshot(cache, instances, sources=(tmp_path / "bench",))

    def fake(family, snap, query):
        calls.append(query)
        if calls[0] == "stop" and len(calls) == 3:
            raise KeyboardInterrupt  # a shard killed during its second query
        return {"lists": {"files": sorted(snap.paths, key=lambda p: p not in query)}, "page": None, "ms": 1.0}

    monkeypatch.setitem(arms.CELLS, "fake", ("fake", "files"))
    monkeypatch.setattr(arms, "run", fake)
    return product, out, cache, instances


def test_retrieve_resumes_and_hits_the_cache(tmp_path, monkeypatch, capsys):
    calls = ["stop"]
    product, _out, cache, instances = _workspace(tmp_path, monkeypatch, calls)
    with pytest.raises(KeyboardInterrupt):
        matrix.retrieve(cache, instances, ["fake"], repo=product)
    assert len(list((cache / "ret").rglob("*.json"))) == 1  # the first query is saved
    calls.clear()
    matrix.retrieve(cache, instances, ["fake"], repo=product)
    assert calls == ["load_config fails", "parse_yaml"]  # the interrupted query and the rest
    calls.clear()
    matrix.retrieve(cache, instances, ["fake"], repo=product)
    assert calls == []  # all cached
    assert capsys.readouterr().out.endswith("retrieve: 0 results made, 3 from the cache\n")
    assert not list(tmp_path.glob("**/.attocode"))


def test_retrieve_refuses_uncommitted_product_code(tmp_path, monkeypatch):
    product, _out, cache, instances = _workspace(tmp_path, monkeypatch, [])
    (product / "packages/code-intel/src/x.py").write_text("x = 2\n")
    with pytest.raises(SystemExit, match="commit the product changes first"):
        matrix.retrieve(cache, instances, ["fake"], repo=product)


def test_rows_feed_the_report(tmp_path, monkeypatch):
    product, out, cache, instances = _workspace(tmp_path, monkeypatch, [])
    matrix.retrieve(cache, instances, ["fake"], repo=product)
    matrix.write_rows(out, cache, instances, ["fake"])
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and set(rows[0]) == {"instance_id", "variant", "cell", "files", "status", "fallback_reason",
                                               "latency_ms", "pool_sha256", "evidence_sha256"}
    assert {r["status"] for r in rows} == {"ok"} and all(len(r["files"]) == 5 for r in rows)  # no png, no link
    monkeypatch.setattr(sys, "argv", ["run", "report", str(out), "--partial"])
    matrix.main()
    assert "| fake@full |" in (out / "report.md").read_text()
    matrix.write_rows(out, cache, instances, ["fake"])  # rewriting replaces the rows of the cell
    assert len((out / "results.jsonl").read_text().splitlines()) == 3


def test_product_families_on_a_small_tree(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    snap = arms.Snapshot(tmp_path, sorted(FILES), timeout=120)
    try:
        product = arms.run("product", snap, "load_config parse_yaml settings")
        assert set(product["lists"]) == {"body", "chunk_fused", "file_bm25", "fused", "keyword"}
        assert product["lists"]["fused"][0] in ("pkg/config.py", "pkg/parse.py") and product["page"] >= 1
        assert product["lists"]["file_bm25"] == []  # whole-file BM25 needs more than 20 words
        noimp = arms.run("product_noimp", snap, "load_config parse_yaml settings")
        assert set(noimp["lists"]) == {"fused"} and set(noimp["lists"]["fused"]) == set(product["lists"]["fused"])
        assert arms.run("repomap", snap, "load_config")["lists"]["files"][0] == "pkg/config.py"
    finally:
        snap.close()


def test_clean_stale_keeps_live_folders(tmp_path):
    finished = subprocess.Popen(["true"])
    finished.wait()
    stale, live = tmp_path / f"attocode-matrix-{finished.pid}-x", tmp_path / f"attocode-matrix-{os.getpid()}-y"
    stale.mkdir()
    live.mkdir()
    matrix._clean_stale(tmp_path)
    assert not stale.exists() and live.exists()
