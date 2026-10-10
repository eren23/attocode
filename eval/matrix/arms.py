"""First-stage arms of the eval matrix. A cell ranks the files of one snapshot for one query.

A family is one call per (snapshot, query). It fills one or more cells:

- ``product``: one traced ``search_candidates`` call with the default scoring. The trace
  also gives the stage cells ``kw`` (name and path BM25), ``body`` (source-body FTS5),
  ``filebm25`` (whole-file BM25, only for a query of more than 20 words) and
  ``chunkrrf`` (keyword and body fused, before whole-file fusion).
- ``product_noimp``: the same call without the importance boost. This is the
  configuration of the published lexical pools (the deleted ``eval.ranking_pair``).
- ``product_auto``: the same call on the query that ``SemanticSearchManager.search``
  expands. The semantic_search tool takes this path by default.
- ``grep``: an agentic-grep stand-in. It greps the code-like terms of the query and
  ranks files by summed idf. Files that the query names by path come first.
- ``repomap``: the order of the repo_map_ranked tool (PageRank and task relevance).
- ``dense``: CodeRankEmbed over the 40-line windows of each source file (``eval.matrix.dense``). It
  reads vectors that a GPU pod made, so it needs no model.

A fused cell (``FUSED``) is the reciprocal-rank fusion of two cells. It has no result of its
own: the stages fuse the cached results of its parts.

A product cell is the file order of the fused candidates before the broad-query rerank.
The default rerank keeps that order, so the page that the product returns is a prefix.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import subprocess
import time
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOP_K = 400  # chunks per product call, as in the published Loc-Bench and blind-pack pools
DEPTH = 200  # files kept per list. Rerank pages of 24 or 48 files and Ceil@48 need fewer.
RELEVANCE_TOP_K = 80  # the chunks that the repo map tool scores (service._task_file_scores)
GREP_VERSION = 1  # change it when the grep rule changes, so that old results are not reused
MAX_TERMS = 40

CELLS = {  # cell -> (family, list)
    "product": ("product", "fused"),
    "kw": ("product", "keyword"),
    "body": ("product", "body"),
    "filebm25": ("product", "file_bm25"),
    "chunkrrf": ("product", "chunk_fused"),
    "product_noimp": ("product_noimp", "fused"),
    "product_auto": ("product_auto", "fused"),
    "grep": ("grep", "files"),
    "repomap": ("repomap", "files"),
    "dense": ("dense", "files"),
    "rrf(product+dense)": ("rrf", "rrf"),
}
FUSED = {"rrf(product+dense)": ("product", "dense")}  # fused cell -> its two cells
RRF_K, RRF_DEPTH = 60, 48  # each part list is cut to 48 files, as in the product fusion
SEARCH = {  # product family -> (SearchScoringConfig overrides, query expansion)
    "product": ({}, False),
    "product_noimp": ({"importance_weight": 0, "frecency_weight": 0}, False),
    "product_auto": ({}, True),
}


class IndexFailedError(RuntimeError):
    """The lexical index did not become ready."""


class NotReadyError(RuntimeError):
    """An input of the family is not there yet, for example the vectors of a file. No result is saved."""


@cache
def engine() -> str:
    """The release gate's hash of the product source, so a product change never reuses a result."""
    spec = importlib.util.spec_from_file_location("release_gate", REPO / "packages/code-intel/evals/release_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.engine_hash(REPO)


def config(family: str) -> dict:
    if family in SEARCH:
        overrides, expand = SEARCH[family]
        return {"engine": engine(), "top_k": TOP_K, "scoring": overrides, "expand": expand, "depth": DEPTH}
    if family == "repomap":
        return {"engine": engine(), "relevance_top_k": RELEVANCE_TOP_K, "depth": DEPTH}
    if family == "dense":
        from eval.matrix import dense
        return {"model": dense.TAG, "depth": DEPTH}
    return {"version": GREP_VERSION, "depth": DEPTH}


def families(cells: list[str]) -> list[str]:
    """The families that make the results of the cells. A fused cell needs the families of its parts."""
    return sorted({CELLS[part][0] for cell in cells for part in FUSED.get(cell, (cell,))})


def rrf(orders: list[list[str]]) -> list[str]:
    scores: dict[str, float] = {}
    for order in orders:
        for rank, path in enumerate(order[:RRF_DEPTH]):
            scores[path] = scores.get(path, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda path: (-scores[path], path))


def fuse(cell: str, parts: list[tuple[str, dict | None]]) -> tuple[str, dict | None]:
    """The key and result of a fused cell from (key, result) of its parts. A missing part gives None."""
    key = hashlib.sha256(json.dumps([cell, [k for k, _r in parts], RRF_K, RRF_DEPTH]).encode()).hexdigest()
    results = [result for _key, result in parts]
    if any(result is None for result in results):
        return key, None
    failed = [result for result in results if result["status"] != "ok"]
    if failed:
        return key, {**failed[0], "lists": {}}
    orders = [result["lists"].get(CELLS[part][1], []) for part, result in zip(FUSED[cell], results, strict=True)]
    return key, {"status": "ok", "lists": {"rrf": rrf(orders)}, "page": None,
                 "ms": round(sum(result["ms"] or 0.0 for result in results), 1)}


def lists(family: str) -> list[str]:
    return sorted({name for fam, name in CELLS.values() if fam == family})


def _ready(manager) -> bool:
    return manager.candidate_diagnostics().get("status") == "ready"


def _search(manager, query: str, top_k: int, timeout: float, trace: dict | None = None,
            tests_last: bool = True) -> list:
    """search_candidates. A call during an index rebuild is repeated, as eval.ranking_pair did."""
    for _attempt in range(3):
        if trace is not None:
            trace.clear()
        found = manager.search_candidates(query, top_k=top_k, trace=trace, tests_last=tests_last)
        if _ready(manager):
            return found
        if not manager.wait_for_body_index(timeout=timeout):
            break
    raise IndexFailedError(f"the index changed during {query[:80]!r}")


_URL = re.compile(r"https?://\S+")
_QUOTED = re.compile(r"`([^`\n]{3,80})`|\"([^\"\n]{3,80})\"|(?<!\w)'([^'\n]{3,80})'(?!\w)")
_PATH = re.compile(r"[\w.-]+(?:/[\w.-]+)+|[\w-]+\.[A-Za-z]{1,10}\b")
_DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
_WORD = re.compile(r"\b[A-Za-z_]\w{2,}\b")
_TEXT_EXTENSIONS = frozenset({".rst", ".txt", ".cfg", ".ini"})


@cache
def _extensions() -> frozenset[str]:
    from attocode_intel._internal.integrations.context.codebase_context import EXTENSION_LANGUAGES
    return frozenset(EXTENSION_LANGUAGES) | _TEXT_EXTENSIONS


def _is_file_name(name: str) -> bool:
    return "." in name and "." + name.rsplit(".", 1)[1].lower() in _extensions()


def _code_like(word: str, text: str, end: int) -> bool:
    """snake_case, camelCase, HTTPServer, or a name followed by a call."""
    return ("_" in word.strip("_") or re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]", word) is not None
            or text[end:end + 1] == "(")


def grep_terms(query: str) -> tuple[list[str], list[str]]:
    """The terms that an agent would grep, in query order, and the path tails that the query names.

    Terms: quoted strings, dotted names and their last part, and code-like words. A tail
    is the last two parts of a named path, or a file name. A traceback path such as
    /usr/lib/site-packages/pkg/mod.py names pkg/mod.py.
    """
    text = _URL.sub(" ", query)
    found: list[tuple[int, str]] = []
    tails: list[str] = []
    for match in _QUOTED.finditer(text):
        quoted = next(group for group in match.groups() if group).strip()
        if len(quoted) >= 3 and "/" not in quoted:  # a quoted path is traceback noise
            found.append((match.start(), quoted))
    for match in _PATH.finditer(text):
        parts = [part for part in match.group().split("/") if part not in ("", ".", "..")]
        if parts and _is_file_name(parts[-1]):
            tail = "/".join(parts[-2:])
            if tail not in tails:
                tails.append(tail)
    for match in _DOTTED.finditer(text):
        parts = match.group().split(".")
        if min(map(len, parts)) < 2 or _is_file_name(match.group()):
            continue
        found += [(match.start(), match.group()), (match.start(), parts[-1])]
    for match in _WORD.finditer(text):
        if _code_like(match.group(), text, match.end()):
            found.append((match.start(), match.group()))
    terms = list(dict.fromkeys(term for _start, term in sorted(found, key=lambda item: item[0])))
    # ponytail: the first terms of a long issue, not its rarest; rank by df if this cap hurts
    return terms[:MAX_TERMS], tails


def _git_grep(root: Path, term: str) -> list[str]:
    done = subprocess.run(["git", "grep", "--no-index", "-l", "-I", "-z", "-F", "-w", "-e", term],
                          cwd=root, capture_output=True, check=False)
    if done.returncode not in (0, 1):
        raise RuntimeError(f"git grep {term!r}: {done.stderr.decode(errors='replace')[:200]}")
    return [path for path in done.stdout.decode(errors="surrogateescape").split("\0") if path]


class Snapshot:
    """A materialized tree. A family builds the product index or the repo graph on first use."""

    def __init__(self, root: Path, paths: list[str], timeout: float = 1800, cache: Path | None = None):
        self.root, self.paths, self.timeout, self.cache = root, paths, timeout, cache
        self._dense = None
        self.index_s = 0.0
        self._manager = None
        self._failed = ""
        self._graph: dict[str, list[str]] | None = None
        self._greps: dict[str, list[str]] = {}

    def manager(self):
        if self._failed:  # one build per snapshot, also when it fails
            raise IndexFailedError(self._failed)
        if self._manager is None:
            from attocode_intel._internal.integrations.context.semantic_search import (
                SemanticSearchManager,
            )
            started = time.perf_counter()
            manager = SemanticSearchManager(str(self.root))
            manager._schedule_body_index()  # the build that a first search starts
            if not manager.wait_for_body_index(timeout=self.timeout) or not _ready(manager):
                self._failed = f"the index was not ready after {self.timeout:.0f} s: {manager.candidate_diagnostics()}"
                manager.close()
                raise IndexFailedError(self._failed)
            self._manager, self.index_s = manager, time.perf_counter() - started
        return self._manager

    def graph(self) -> dict[str, list[str]]:
        """The import graph that the repo map tool ranks: file -> imported files."""
        if self._graph is None:
            from attocode_intel._internal.integrations.context.codebase_context import (
                CodebaseContextManager,
            )
            context = CodebaseContextManager(root_dir=str(self.root))
            context._ensure_fresh()
            if not context._files:
                context.discover_files()
            imports = context._dep_graph
            self._graph = {info.relative_path: list(imports.get_imports(info.relative_path)) if imports else []
                           for info in context._files}
        return self._graph

    def dense_vectors(self):
        """The window vectors of the snapshot, from the cache. Raises NotReadyError when one is missing."""
        from eval.matrix import dense
        if self._dense is None:
            try:
                self._dense = dense.vectors(dense.store(self.cache), self.root, self.paths)
            except dense.MissingVectorsError as error:
                self._dense = error
        if isinstance(self._dense, Exception):
            raise NotReadyError(str(self._dense))
        return self._dense

    def dense(self, query: str) -> list[str]:
        from eval.matrix import dense
        found = dense.store(self.cache).get(dense.query_key(query))
        if found is None:
            raise NotReadyError(f"no vector for the query {query[:80]!r}")
        return dense.rank(*self.dense_vectors(), found[0], DEPTH)

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close()
            self._manager = None

    def grep(self, query: str) -> list[str]:
        terms, tails = grep_terms(query)
        known = set(self.paths)
        scores: dict[str, float] = {}
        for term in terms:
            if term not in self._greps:  # ponytail: per snapshot, as the full and title queries share terms
                self._greps[term] = [path for path in _git_grep(self.root, term) if path in known]
            hits = self._greps[term]
            for path in hits:
                scores[path] = scores.get(path, 0.0) + math.log(1 + len(self.paths) / len(hits))
        named = {path for path in self.paths for tail in tails if path == tail or path.endswith("/" + tail)}
        ranked = sorted(set(scores) | named, key=lambda path: (path not in named, -scores.get(path, 0.0), path))
        return ranked[:DEPTH]

    def repomap(self, query: str) -> list[str]:
        """The repo_map_ranked tool: PageRank over imports, weighted by search relevance and path words."""
        from attocode_intel._internal.integrations.context.semantic_search import (
            SearchScoringConfig,
        )
        from attocode_intel.repo_ranker import rank_repo_files
        manager = self.manager()
        manager.scoring_config = SearchScoringConfig()
        relevance: dict[str, float] = {}  # as service._task_file_scores
        for rank, result in enumerate(_search(manager, query, RELEVANCE_TOP_K, self.timeout, tests_last=False)):
            relevance[result.file_path] = max(relevance.get(result.file_path, 0.0), 1.0 / (1.0 + rank / 10.0))
        ranked = rank_repo_files(self.graph(), task_context=query, token_budget=10**12, relevance_by_file=relevance)
        return [entry.path for entry in ranked.entries[:DEPTH]]


def run(family: str, snapshot: Snapshot, query: str) -> dict:
    """One family call: {"lists": {name: files}, "page": files on the returned page, "ms": call time}.

    The time excludes the index build and the import graph, which a snapshot builds once.
    """
    page = None
    if family in SEARCH:
        from attocode_intel._internal.integrations.context.semantic_search import (
            SearchScoringConfig,
            _expand_query,
        )
        overrides, expand = SEARCH[family]
        manager = snapshot.manager()
        started = time.perf_counter()
        manager.scoring_config = SearchScoringConfig(**overrides)
        trace: dict = {}
        found = _search(manager, _expand_query(query, "") if expand else query, TOP_K, snapshot.timeout, trace)
        out = {name: trace.get(name, [])[:DEPTH] for name in lists(family)}
        page = len({result.file_path for result in found})
    elif family == "repomap":
        snapshot.manager()
        snapshot.graph()
        started = time.perf_counter()
        out = {"files": snapshot.repomap(query)}
    elif family == "dense":
        snapshot.dense_vectors()
        started = time.perf_counter()
        out = {"files": snapshot.dense(query)}
    else:
        started = time.perf_counter()
        out = {"files": snapshot.grep(query)}
    return {"lists": out, "page": page, "ms": round((time.perf_counter() - started) * 1000, 1)}
