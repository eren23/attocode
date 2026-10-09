"""Dense first-stage arm of the eval matrix: CodeRankEmbed over the 40-line windows of each file.

The arm embeds and ranks the source files of product search (``ranked``): no docs and no data.
A file scores the best cosine of its windows with the query. A GPU pod embeds the files and
the queries once. The vectors go into the matrix cache under ``emb/<TAG>/``, keyed by
(path, blob oid) and by query, so the retrieve stage scores on any computer without a model.

  python -m eval.matrix.dense plan OUT --job JOB.json [--ids FILE] [--dataset NAME]
      Write the snapshots (with a GitHub name) and the queries of OUT/instances.jsonl.
      Only datasets with `public: true` in configs/full.yaml can go to the pod.
  python -m eval.matrix.dense job JOB.json --work DIR [--workers N] [--limit N] [--sdpa]
      On the pod: snapshot the repositories with the eval.matrix.run code, then embed. --limit
      stops after about N windows, to measure the throughput. --sdpa uses the fused attention
      of PyTorch in the model (check the parity with `parity` first).
  python -m eval.matrix.dense import DIR [--cache DIR]
      Compare the trees of the pod with the local trees, then add the vectors to the cache (a hard
      link on the same disk). An import can run again after each copy of new parts from the pod.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

from eval.matrix import datasets, run

MODEL = "nomic-ai/CodeRankEmbed"
MODEL_REVISION = "3c4b60807d71f79b43f3c4363786d9493691f8b1"  # pins the remote modeling code too
QUERY_PREFIX = "Represent this query for searching relevant code: "  # from the model card
WINDOW, MAX_WINDOWS, MAX_CHARS = 40, 400, 1500  # 400 windows: the first 16,000 lines of a file
QUERY_SEQ, WINDOW_SEQ = 2048, 512  # token limits; the model trained on 2,048 positions
TAG = f"coderankembed-{MODEL_REVISION[:12]}-w{WINDOW}x{MAX_WINDOWS}-c{MAX_CHARS}-q{QUERY_SEQ}-s{WINDOW_SEQ}-v2"
PART_WINDOWS = 200_000  # windows per stored part: about 300 MB of fp16 vectors


def ranked(path: str) -> bool:
    """A file that the arm embeds and ranks: a source file by the rule of the product's whole-file BM25.

    Product search parses the file, and it is not prose or data (markdown, YAML, JSON and so on).
    """
    from attocode_intel._internal.integrations.context.semantic_search import _NON_CODE_EXTS
    return datasets.search_coverage(path) == "parsed" and os.path.splitext(path)[1].lower() not in _NON_CODE_EXTS


def windows(path: str, data: bytes) -> list[str]:
    """The texts that the model embeds for a file. A binary file has none."""
    if b"\0" in data[:4096]:
        return []
    lines = data.decode(errors="replace").splitlines()
    starts = range(0, max(len(lines), 1), WINDOW)[:MAX_WINDOWS]
    return [f"File: {path}\n{chr(10).join(lines[start:start + WINDOW])}"[:MAX_CHARS] for start in starts]


def file_key(path: str, oid: str) -> str:
    return hashlib.sha256(f"{path}\0{oid}".encode()).hexdigest()[:32]


def query_key(query: str) -> str:
    return hashlib.sha256(f"query\0{query}".encode()).hexdigest()[:32]


def git_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class Store:
    """Vectors in parts: PART.npy (fp16, one row per window or query) and PART.json (key -> [start, count]).

    A part never changes. Its name is the hash of its index, and the index is written last.
    """

    def __init__(self, root: Path):
        self.root = root
        self._index: dict[str, tuple[str, int, int]] | None = None
        self._parts: dict[str, np.ndarray] = {}

    def index(self) -> dict[str, tuple[str, int, int]]:
        # ponytail: one dict for all parts, about 200 bytes a file; shard by repository past a few million files
        if self._index is None:
            self._index = {}
            for meta in sorted(self.root.glob("*.json")):
                for key, (start, count) in json.loads(meta.read_text()).items():
                    self._index[key] = (meta.stem, start, count)
        return self._index

    def get(self, key: str) -> np.ndarray | None:
        hit = self.index().get(key)
        if hit is None:
            return None
        part, start, count = hit
        if part not in self._parts:
            self._parts[part] = np.load(self.root / f"{part}.npy", mmap_mode="r")
        return self._parts[part][start:start + count]

    def add(self, keys: list[str], counts: list[int], vectors: np.ndarray) -> str:
        if sum(counts) != len(vectors):
            raise ValueError(f"{sum(counts)} rows in the index, {len(vectors)} vectors")
        index, start = {}, 0
        for key, count in zip(keys, counts, strict=True):
            index[key] = [start, count]
            start += count
        text = json.dumps(index, sort_keys=True)
        part = hashlib.sha256(text.encode()).hexdigest()[:16]
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.root / f".{part}.{os.getpid()}.tmp"
        with temp.open("wb") as handle:
            np.save(handle, vectors.astype(np.float16))
        os.replace(temp, self.root / f"{part}.npy")
        run._write(self.root / f"{part}.json", text.encode())
        if self._index is not None:
            self._index.update({key: (part, begin, count) for key, (begin, count) in index.items()})
        return part


@cache
def store(cache_dir: Path) -> Store:
    return Store(cache_dir / "emb" / TAG)


class MissingVectorsError(LookupError):
    """The store has no vector for a file or a query of the snapshot."""


def vectors(vecs: Store, root: Path, paths: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """The files with windows, the first row of each file, and the window vectors (float32)."""
    names, starts, rows, at = [], [], [], 0
    for path in filter(ranked, paths):
        data = (root / path).read_bytes()
        found = vecs.get(file_key(path, git_oid(data)))
        if found is None:
            if b"\0" in data[:4096]:
                continue  # a binary file has no windows
            raise MissingVectorsError(f"no vectors for {path}")
        names.append(path)
        starts.append(at)
        rows.append(found)
        at += len(found)
    matrix = np.vstack(rows).astype(np.float32) if rows else np.zeros((0, 1), np.float32)
    return names, np.array(starts, dtype=np.int64), matrix


def rank(names: list[str], starts: np.ndarray, matrix: np.ndarray, query: np.ndarray, depth: int) -> list[str]:
    """Files by the best cosine of their windows, ties by path."""
    if not names:
        return []
    best = np.maximum.reduceat(matrix @ query.astype(np.float32), starts)
    order = sorted(range(len(names)), key=lambda i: (-best[i], names[i]))
    return [names[i] for i in order[:depth]]


def _github(repo: str) -> str:
    """The GitHub owner/name of a repository key. A case-pack key names a local clone."""
    if "/" in repo:
        return repo
    local = run._local(repo, run.SOURCES)
    url = run._git(local, "remote", "get-url", "origin").decode().strip() if local else ""
    name = url.removesuffix(".git").replace(":", "/").split("github.com/")[-1]
    if not local or "github.com" not in url or name.count("/") != 1:
        raise SystemExit(f"no GitHub clone URL for {repo}: {url or 'no local clone'}")
    return name


def plan(out: Path, job: Path, ids: Path | None, dataset: str | None) -> None:
    instances = run._select_ids(run._instances(out), ids)
    if dataset:
        instances = [inst for inst in instances if inst.dataset == dataset]
    config = yaml.safe_load((Path(__file__).resolve().parent / "configs/full.yaml").read_text())["datasets"]
    private = sorted({inst.dataset for inst in instances if not config.get(inst.dataset, {}).get("public")})
    if private:
        raise SystemExit(f"refused: {', '.join(private)} is not public: true, so it cannot go to the pod")
    pairs = sorted({(inst.repo, inst.base_commit) for inst in instances})
    names = {repo: _github(repo) for repo in sorted({repo for repo, _commit in pairs})}
    snapshots = [{"key": repo, "repo": names[repo], "commit": commit} for repo, commit in pairs]
    queries = sorted({query for inst in instances for query in inst.queries.values()})
    run._write(job, json.dumps({"tag": TAG, "snapshots": snapshots, "queries": queries}, indent=1).encode())
    print(f"{job}: {len(snapshots)} snapshots of {len(names)} repositories, {len(queries)} queries")


def _snapshot_shard(cache_dir: str, items: list[tuple[str, str]]) -> None:
    run.MIN_FREE = 2 * 2**30  # ponytail: the pod disk; the 25 GiB floor is for the Mac
    run.snapshot(Path(cache_dir), [SimpleNamespace(repo=repo, base_commit=commit) for repo, commit in items],
                 sources=())


def digest(tree: dict) -> str:
    """The stored regular files of a tree: the files that the dense arm ranks."""
    rows = sorted(f"{path}\0{oid}" for path, mode, oid, size in tree["entries"]
                  if mode != "120000" and run._stored([path, mode, oid, size]))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _sdpa_forward(self, hidden_states, attention_mask=None, *_args, **_kwargs):
    """NomicBertAttention.forward of the model code, with the fused attention of PyTorch.

    The same steps as the model code for an encoder in eval mode: no cache and no dropout.
    """
    import torch.nn.functional as F  # noqa: N812
    from einops import rearrange

    qkv = rearrange(self.Wqkv(hidden_states), "... (three h d) -> ... three h d", three=3, d=self.head_dim)
    if self.rotary_emb_dim > 0:
        if self.rotary_head_dim:
            qkv = rearrange(qkv, "b s three h d -> b h three s d")
        qkv = self.rotary_emb(qkv, seqlen_offset=0)
        if self.rotary_head_dim:
            qkv = rearrange(qkv, "b h three s d -> b s three h d")
    query, key, value = (qkv[:, :, part].permute(0, 2, 1, 3) for part in range(3))
    out = F.scaled_dot_product_attention(query, key, value, attn_mask=attention_mask)  # scale 1/sqrt(head_dim)
    return self.out_proj(rearrange(out.permute(0, 2, 1, 3), "... h d -> ... (h d)"))


def encode(model, texts: list[str], *, seq: int, batch: int) -> np.ndarray:
    model.max_seq_length = seq
    return model.encode(texts, batch_size=batch, normalize_embeddings=True, convert_to_numpy=True)


def use_sdpa(model, samples: list[tuple[list[str], int]], batch: int) -> float:
    """Switch the model to fused attention when the vectors stay the same: lowest cosine 0.9999 or more."""
    before = [encode(model, texts, seq=seq, batch=batch) for texts, seq in samples]
    attention = next(type(module) for module in model.modules() if type(module).__name__ == "NomicBertAttention")
    original, attention.forward = attention.forward, _sdpa_forward
    after = [encode(model, texts, seq=seq, batch=batch) for texts, seq in samples]
    low = min(float(np.min(np.sum(a.astype(np.float32) * b.astype(np.float32), axis=1)))
              for a, b in zip(before, after, strict=True))
    if low < 0.9999:
        attention.forward = original
    return low


def job(spec_path: Path, work: Path, *, workers: int, limit: int | None, batch: int, sdpa: bool = False) -> None:
    spec = json.loads(spec_path.read_text())
    if spec["tag"] != TAG:
        raise SystemExit(f"the job is for {spec['tag']}, this code embeds {TAG}")
    matrix = work / "matrix"
    shards: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for index, repo in enumerate(sorted({item["repo"] for item in spec["snapshots"]})):
        shards[index % workers] += [(item["repo"], item["commit"]) for item in spec["snapshots"] if item["repo"] == repo]
    started = time.time()
    with ProcessPoolExecutor(workers) as pool:
        for done in [pool.submit(_snapshot_shard, str(matrix), items) for items in shards.values()]:
            done.result()
    manifest, files = [], {}
    for item in spec["snapshots"]:
        tree = json.loads(run._tree_file(matrix, item["repo"], item["commit"]).read_text())
        manifest.append({**item, "tree": tree.get("tree"), "error": tree.get("error"),
                         "stored": None if "error" in tree else digest(tree)})
        for path, mode, oid, size in tree.get("entries", []):
            if mode != "120000" and run._stored([path, mode, oid, size]) and ranked(path):
                files.setdefault(file_key(path, oid), (path, oid))
    run._write(work / "manifest.json", json.dumps({"tag": TAG, "snapshots": manifest}, indent=1).encode())
    print(f"snapshots: {len(manifest)} ({sum(bool(m['error']) for m in manifest)} failed), {len(files)} files, "
          f"{time.time() - started:.0f} s", flush=True)

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, revision=MODEL_REVISION, trust_remote_code=True, device="cuda")
    model.half()
    vecs = Store(work / "emb" / TAG)
    queries = [query for query in spec["queries"] if vecs.get(query_key(query)) is None]
    prefixed = [QUERY_PREFIX + query for query in queries]
    # In the order of the job, so that the first snapshots of a job that stops early are complete
    todo = [(key, path, oid) for key, (path, oid) in files.items() if vecs.get(key) is None]
    if sdpa:
        sample = [text for _key, path, oid in todo[:200]
                  for text in windows(path, zlib.decompress(run._blob_file(matrix, oid).read_bytes()))][:512]
        low = use_sdpa(model, [(sample, WINDOW_SEQ), (prefixed[:32], QUERY_SEQ)], batch=max(batch // 8, 1))
        print(f"sdpa: lowest cosine {low:.6f} on {len(sample)} windows and {len(prefixed[:32])} queries, "
              f"{'used' if low >= 0.9999 else 'not used'}", flush=True)
    if queries:  # a query is up to 4 times as long as a window, so the batch is smaller
        found = encode(model, prefixed, seq=QUERY_SEQ, batch=max(batch // 8, 1))
        vecs.add([query_key(query) for query in queries], [1] * len(queries), found)
    total, embedded, started = len(todo), 0, time.time()
    keys, counts, texts = [], [], []
    for number, (key, path, oid) in enumerate(todo, 1):
        found = windows(path, zlib.decompress(run._blob_file(matrix, oid).read_bytes()))
        if found:
            keys.append(key)
            counts.append(len(found))
            texts += found
        if texts and (len(texts) >= PART_WINDOWS or number == total or (limit and len(texts) >= limit)):
            out = encode(model, texts, seq=WINDOW_SEQ, batch=batch)
            part = vecs.add(keys, counts, out)
            embedded += len(texts)
            rate = embedded / (time.time() - started)
            print(f"part {part}: {len(keys)} files, {len(texts)} windows; {number}/{total} files, "
                  f"{rate:.0f} windows/s overall", flush=True)
            keys, counts, texts = [], [], []
            if limit and embedded >= limit:
                return
    print(f"embedded {embedded} windows of {total} files in {time.time() - started:.0f} s", flush=True)


def import_(work: Path, cache_dir: Path) -> None:
    manifest = json.loads((work / "manifest.json").read_text())
    if manifest["tag"] != TAG:
        raise SystemExit(f"the pod embedded {manifest['tag']}, this code reads {TAG}")
    same, other = 0, []
    for item in manifest["snapshots"]:
        path = run._tree_file(cache_dir, item["key"], item["commit"])
        local = json.loads(path.read_text()) if path.exists() else {"error": "no local snapshot"}
        if "error" in local or item["error"] or local.get("tree") != item["tree"] or digest(local) != item["stored"]:
            other.append(f"{item['key']}@{item['commit'][:12]}: pod {item['error'] or item['tree']}, "
                         f"local {local.get('error') or local.get('tree')}")
        else:
            same += 1
    source, target = work / "emb" / TAG, cache_dir / "emb" / TAG
    target.mkdir(parents=True, exist_ok=True)
    added = 0
    for meta in sorted(source.glob("*.json")):
        npy = meta.with_suffix(".npy")
        if not (target / meta.name).exists() and npy.exists():
            if not (target / npy.name).exists():
                try:
                    os.link(npy, target / npy.name)  # on the same disk, no second copy of GBs of vectors
                except OSError:
                    shutil.copyfile(npy, target / npy.name)
            shutil.copyfile(meta, target / meta.name)  # the index last: a part with an index is complete
            added += 1
    print(f"trees: {same} equal to the local trees, {len(other)} not" + "".join(f"\n  {row}" for row in other))
    print(f"added {added} parts to {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="write the job of a run folder")
    planning.add_argument("out", type=Path)
    planning.add_argument("--job", type=Path, required=True)
    planning.add_argument("--ids", type=Path)
    planning.add_argument("--dataset")
    working = commands.add_parser("job", help="snapshot and embed, on the GPU pod")
    working.add_argument("spec", type=Path)
    working.add_argument("--work", type=Path, required=True)
    working.add_argument("--workers", type=int, default=16)
    working.add_argument("--limit", type=int, help="stop after about this many windows")
    working.add_argument("--batch", type=int, default=128)
    working.add_argument("--sdpa", action="store_true", help="fused attention, when a sample keeps the vectors")
    importing = commands.add_parser("import", help="check the pod trees and add the vectors to the cache")
    importing.add_argument("work", type=Path)
    importing.add_argument("--cache", type=Path, default=run.CACHE)
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.out, args.job, args.ids, args.dataset)
    elif args.command == "job":
        job(args.spec, args.work, workers=args.workers, limit=args.limit, batch=args.batch, sdpa=args.sdpa)
    else:
        import_(args.work, args.cache)


if __name__ == "__main__":
    main()
