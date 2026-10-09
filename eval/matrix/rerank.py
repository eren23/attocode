"""Rerank arms of the eval matrix, the cache of their outputs, and the ledger of paid calls.

A rerank cell reorders the first PAGE files of a first-stage cell (its pool) for one query.
The rest of the pool follows unchanged. The cell name is POOL>ARM.PAGE, plus .qN when the arm
gets only the first N characters of the query, and ~rI for repeat I (repeat 0 has no suffix).

Every arm sees the same evidence: ``focused_evidence.file_excerpt`` of each file, made with
the whole query. cache.db (SQLite, WAL mode) keeps the outputs. A listwise arm has one entry
per (arm, revision, prompt version, query sent, evidence hash, repeat). The evidence hash is
the ``evidence_sha256`` of the old trials (the excerpts in page order, joined by newlines), so
``run.py import-legacy`` can load old Jev answers. A pointwise arm has one entry per (arm,
revision, prompt version, query sent, excerpt hash).

The ledger has one row per paid call. A call reserves its estimated cost before it starts, so
threads and parallel shards cannot spend past the cap together. A failed request, an invalid
answer and a missing file are statuses: their rows keep the pool order, and the report counts
them. A job that the cap stopped gets no row.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from eval.matrix.datasets import Instance

OPENROUTER = "https://openrouter.ai/api/v1"
JEV_MODEL = "typesafe/jev-1.13"  # the model of the old trials, as attocode_intel.confidence.jev sends it
JEV_USD_PER_CALL = 0.0006  # measured: $0.96 for 1,670 calls (whole-file BM25 run), $0.58 for 930 (q512 run)
PROBE_CALLS = 5  # paid calls that measure the cost of an arm that has no ledger history
PROBE_USD = 0.05  # the reservation of one probe call
MARGIN = 1.5  # a call reserves its measured estimate times this, so a long call cannot pass the cap
CREDITS_EVERY = 200  # paid calls between two checks of the OpenRouter usage counter
WORKERS = 4
MAX_LENGTH = 1024  # tokens per local pair: a 512-character query and a 1,350-character excerpt fit
INSTRUCTION = ("Find implementation files that help a developer investigate the code-navigation query. "
               "Prefer behavioral evidence over incidental keyword overlap.")
QWEN_PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the '
               'Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
LISTWISE = ("You rank source files for a code-navigation query: an issue report or a question about one "
            "repository. Each candidate is a numbered excerpt of one file. Rank the candidates by how likely a "
            "developer must read or edit the file to resolve the query. Answer with only a JSON array that holds "
            "every candidate number once, most likely first, for example [3, 0, 2, 1].")
# Prompt 1 put the format rule only in the system prompt. Haiku 4.5 then wrote prose before the
# array for 6 of 10 issues. Prompt 2 repeats the rule after the candidates and starts the answer.
LISTWISE_END = "Answer with only the JSON array of all {count} candidate numbers, most likely first."

# kind: none (the pool order), cross (local pointwise model), jev, listwise (chat model) or http
# (the product SystemOne adapter). A remote arm sends excerpts out of this machine, and a paid arm
# goes through the ledger. Add "prompt": 2 when the prompt or the input format of an arm changes.
ARMS = {
    "none": {"kind": "none"},
    # The sequence-classification port of Qwen/Qwen3-Reranker-0.6B. The official repository now
    # ships a LogitScore layout that needs sentence-transformers 5.4.
    "qwen3-rr-0.6b": {"kind": "cross", "model": "tomaarsen/Qwen3-Reranker-0.6B-seq-cls",
                      "revision": "6a5829f5079c66e78d911e06fe21931cc00232f7", "template": "qwen3", "batch": 1},
    "bge-rr-v2-m3": {"kind": "cross", "model": "BAAI/bge-reranker-v2-m3",
                     "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "batch": 8},
    "jina-rr-v2": {"kind": "cross", "model": "jinaai/jina-reranker-v2-base-multilingual",
                   "revision": "9cfeff2df7d40d1b78e75e5e9cebec92a99813c9", "batch": 8, "remote_code": True},
    "gte-modernbert-rr": {"kind": "cross", "model": "Alibaba-NLP/gte-reranker-modernbert-base",
                          "revision": "f7481e6055501a30fb19d090657df9ec1f79ab2c", "batch": 8},
    "mxbai-rr-base-v2": {"kind": "cross", "model": "mixedbread-ai/mxbai-rerank-base-v2",
                         "revision": "3ea9d4dffa7d12a4f366be8e275c349de9fc9865", "batch": 1, "min_st": (5, 4)},
    "systemone-http": {"kind": "http"},
    "jev-choice": {"kind": "jev", "remote": True, "paid": True},
    "haiku45-listwise": {"kind": "listwise", "model": "anthropic/claude-haiku-4.5", "remote": True, "paid": True,
                         "prompt": 2},
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def evidence_hash(excerpts: list[str]) -> str:
    return _sha("\n".join(excerpts))


def listwise_key(arm: str, revision: str, prompt: int, query: str, evidence: str, repeat: int) -> str:
    return _sha(json.dumps([arm, revision, prompt, query, evidence, repeat]))


def pointwise_key(arm: str, revision: str, prompt: int, query: str, excerpt: str) -> str:
    return _sha(json.dumps([arm, revision, prompt, query, _sha(excerpt)]))


def cell_name(pool: str, arm: str, page: int, chars: int = 0, repeat: int = 0) -> str:
    return f"{pool}>{arm}.{page}" + (f".q{chars}" if chars else "") + (f"~r{repeat}" if repeat else "")


def remote(arm: str, entry: dict) -> bool:
    """True when the arm sends excerpts out of this machine. Only a loopback IP literal is local."""
    if ARMS[arm]["kind"] != "http":
        return bool(ARMS[arm].get("remote"))
    try:
        return not ipaddress.ip_address(urlsplit(entry.get("endpoint", "")).hostname or "").is_loopback
    except ValueError:
        return True


def revision(arm: str, entry: dict) -> str:
    spec = ARMS[arm]
    if spec["kind"] == "jev":
        return os.environ.get("JEV_MODEL", JEV_MODEL)
    if spec["kind"] == "http":
        return f"{entry.get('model_id', '')}@{_sha(entry.get('endpoint', ''))[:12]}"
    return spec.get("revision") or spec.get("model", "")


@dataclass
class Job:
    """One rerank row to make: a cell, an instance and a query variant."""
    cell: str
    arm: str
    entry: dict
    inst: Instance
    variant: str
    pool_cell: str
    pool: dict  # the row of the pool cell
    page: int
    chars: int = 0
    repeat: int = 0
    paths: list[str] = field(default_factory=list)
    excerpts: list[str] = field(default_factory=list)
    query: str = ""  # the query that the arm gets
    evidence: str | None = None
    key: str | None = None
    output: dict | None = None
    cache_hit: bool = False


def plan(cfg: dict, instances: list[Instance], pools: dict[tuple[str, str, str], dict]) -> tuple[list[Job], int]:
    """The jobs of the config's rerank entries in config order, and the count of pools without a row.

    An entry runs on the instances with the tag or the dataset in ``on`` (default all). The arms
    in ``repeats`` run n - 1 more times on the instances of ``repeats.on``.
    """
    def on(item: dict, default: str) -> str:
        return item.get("on", item.get(True, default))  # YAML 1.1 reads a bare on: key as True

    repeats = cfg.get("repeats") or {}
    jobs: dict[tuple[str, str, str], Job] = {}
    missing = 0
    for entry in cfg.get("rerank") or []:
        arm = entry["arm"]
        if arm not in ARMS:
            raise SystemExit(f"unknown rerank arm {arm}. Known arms: {', '.join(ARMS)}")
        if ARMS[arm]["kind"] == "http" and not entry.get("endpoint"):
            raise SystemExit(f"{arm} needs an endpoint in its rerank entry")
        runs = [(0, on(entry, "all"))]
        if arm in repeats.get("arms", []):
            runs += [(r, on(repeats, "noise50")) for r in range(1, repeats.get("n", 1))]
        for repeat, scope in runs:
            for inst in instances:
                if scope not in ("all", inst.dataset, *inst.tags):
                    continue
                for variant in entry.get("variants") or list(inst.queries):
                    for pool_cell in entry["pools"]:
                        pool = pools.get((inst.id, variant, pool_cell))
                        if pool is None:
                            missing += variant in inst.queries
                            continue
                        for page in entry["pages"]:
                            for chars in entry.get("query_chars") or [0]:
                                cell = cell_name(pool_cell, arm, page, chars, repeat)
                                jobs.setdefault((inst.id, variant, cell), Job(
                                    cell, arm, entry, inst, variant, pool_cell, pool, page, chars, repeat))
    return list(jobs.values()), missing


class Cache:
    """cache.db: model outputs and the ledger. One connection, safe for threads and for parallel shards."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60, isolation_level=None, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS outputs (key TEXT PRIMARY KEY, arm TEXT, value TEXT, created REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY, run TEXT, arm TEXT, key TEXT, "
                        "units INTEGER, cost_usd REAL, state TEXT, created REAL)")

    def get(self, key: str) -> dict | None:
        with self.lock:
            found = self.db.execute("SELECT value FROM outputs WHERE key = ?", (key,)).fetchone()
        return json.loads(found[0]) if found else None

    def put(self, key: str, arm: str, value: dict, *, replace: bool = True) -> int:
        """Store an output. Returns 1 when it wrote a row."""
        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
        with self.lock:
            return self.db.execute(f"{verb} INTO outputs VALUES (?, ?, ?, ?)",
                                   (key, arm, json.dumps(value), time.time())).rowcount

    def spent(self, run: str) -> float:
        """The cost of the run's paid calls. A call in flight counts with its reservation."""
        with self.lock:
            return self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ledger WHERE run = ?", (run,)).fetchone()[0]

    def reserve(self, run: str, arm: str, key: str, units: int, estimate: float, cap: float) -> int | None:
        """A ledger row for one paid call, or None when the call could pass the cap."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")  # other shards wait, so the check and the insert are one step
            try:
                spent = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ledger WHERE run = ?",
                                        (run,)).fetchone()[0]
                if spent + estimate > cap + 1e-9:
                    return None
                return self.db.execute("INSERT INTO ledger (run, arm, key, units, cost_usd, state, created) "
                                       "VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                                       (run, arm, key, units, estimate, time.time())).lastrowid
            finally:
                self.db.execute("COMMIT")

    def settle(self, row: int, cost: float, state: str) -> None:
        with self.lock:
            self.db.execute("UPDATE ledger SET cost_usd = ?, state = ? WHERE id = ?", (cost, state, row))

    def add(self, run: str, arm: str, cost: float, state: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO ledger (run, arm, key, units, cost_usd, state, created) "
                            "VALUES (?, ?, '', 0, ?, ?, ?)", (run, arm, cost, state, time.time()))

    def unit_cost(self, arm: str) -> float | None:
        """Mean cost per candidate of the arm's last 50 calls with a provider-reported cost, in any run."""
        with self.lock:
            rows = self.db.execute("SELECT cost_usd, units FROM ledger WHERE arm = ? AND state = 'actual' "
                                   "AND units > 0 ORDER BY id DESC LIMIT 50", (arm,)).fetchall()
        return sum(cost for cost, _u in rows) / sum(units for _c, units in rows) if rows else None


def ledger(path: Path, run: str) -> dict[str, tuple[int, float]]:
    """(paid calls, cost) per arm of a run. It opens cache.db read-only."""
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT arm, COUNT(*), SUM(cost_usd) FROM ledger WHERE run = ? GROUP BY arm",
                          (run,)).fetchall()
    finally:
        db.close()
    return {arm: (calls, cost) for arm, calls, cost in rows}


@functools.cache
def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        from dotenv import dotenv_values
        key = dotenv_values(Path.home() / ".jev/env").get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("the remote arms need OPENROUTER_API_KEY, in the environment or in ~/.jev/env")
    return key


def openrouter_usage() -> float | None:
    """The OpenRouter usage counter of the key in USD, or None when the request fails."""
    import httpx
    try:
        response = httpx.get(f"{OPENROUTER}/credits", headers={"Authorization": f"Bearer {openrouter_key()}"},
                             timeout=30)
        response.raise_for_status()
        return float(response.json()["data"]["total_usage"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None


class Budget:
    """The cap of a run. Every CREDITS_EVERY paid calls, it compares the ledger with the OpenRouter
    usage counter. When the counter grew more than 25% over the ledger, the difference goes into
    the ledger, so the cap counts it. Other use of the same key also moves the counter."""

    def __init__(self, cache: Cache, run: str, cap: float, *, check_credits: bool = True):
        self.cache, self.run, self.cap, self.check_credits = cache, run, cap, check_credits
        self.calls, self.started, self.stopped = 0, False, threading.Event()
        self.lock = threading.Lock()
        self.base_usage: float | None = None
        self.base_spent = 0.0

    def call(self, arm: str, key: str, units: int, estimate: float, ask) -> dict | None:
        """Run a paid call inside the cap. None when the cap stops the call, and then all later calls."""
        with self.lock:
            if not self.started:  # the baseline of the usage check, at the first paid call
                self.started = True
                self.base_usage = openrouter_usage() if self.check_credits else None
                self.base_spent = self.cache.spent(self.run)
        if self.stopped.is_set():
            return None
        row = self.cache.reserve(self.run, arm, key, units, estimate, self.cap)
        if row is None:
            self.stopped.set()
            return None
        output = None
        try:
            output = ask()
        finally:
            reported = output is not None and output.get("cost_usd") is not None
            cost = output["cost_usd"] if reported else estimate
            self.cache.settle(row, cost, "actual" if reported else "estimated")
        output |= {"cost_usd": cost, "cost_source": "provider" if reported else "estimate"}
        with self.lock:
            self.calls += 1
            check = self.calls % CREDITS_EVERY == 0
        if check:
            self.check()
        return output

    def check(self) -> None:
        usage = openrouter_usage() if self.base_usage is not None else None
        if usage is None:
            return
        real, counted = usage - self.base_usage, self.cache.spent(self.run) - self.base_spent
        print(f"credits check: OpenRouter usage +${real:.4f}, ledger +${counted:.4f}", flush=True)
        if real > counted * 1.25 + 0.01:
            self.cache.add(self.run, "openrouter-usage", real - counted, "credits")
            self.base_spent += real - counted


def _done(status: str, started: float, order: list[int] | None = None, **extra) -> dict:
    return {"status": status, "order": order, "error": None, "ms": round((time.perf_counter() - started) * 1000, 1),
            "cost_usd": None, **extra}


def _ranked(scores: list[float], started: float, **extra) -> dict:
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))  # a tie keeps the pool order
    return _done("ok", started, order, scores=[round(float(s), 5) for s in scores], **extra)


def jev_choice(query: str, excerpts: list[str]) -> dict:
    """One Jev choice over the page, with the request of the old trials. The probabilities rank the files."""
    from attocode_intel.confidence.jev import _decide
    from attocode_intel.confidence.redact import redact

    os.environ["OPENROUTER_API_KEY"] = openrouter_key()  # _decide reads the key from the environment
    question = {"best": {"type": "choice",
                         "instructions": "Which source file most directly implements the behavior in the query?",
                         "criteria": {str(i): redact(text) for i, text in enumerate(excerpts)}}}
    state = {"query": redact(query), "task": redact("Find the primary implementation file, not an incidental match.")}
    started = time.perf_counter()
    try:
        result = _decide("attocode_search_choice_trial", state, question, "0", "openrouter")
    except Exception as error:  # noqa: BLE001 - any transport or server error is a failed request
        return _done("request_failed", started, error=f"{type(error).__name__}: {error}"[:300])
    probs = ((result.get("answers") or {}).get("best") or {}).get("probabilities")
    scores = [probs.get(str(i)) for i in range(len(excerpts))] if isinstance(probs, dict) else [None]
    if any(isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or not 0 <= v <= 1
           for v in scores):
        return _done("invalid_output", started, error=f"no valid choice probabilities: {probs!r}"[:300])
    return _ranked(scores, started)


def index_list(text: str, count: int) -> list[int] | None:
    """The order in a listwise answer: a JSON array with every candidate number once. A code fence is allowed."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        items = json.loads(text)
    except ValueError:
        return None
    if not isinstance(items, list) or not all(type(i) is int for i in items) or sorted(items) != list(range(count)):
        return None
    return items


def listwise(model: str, query: str, excerpts: list[str]) -> dict:
    """One OpenRouter chat call that orders the page. OpenRouter reports the cost of the call."""
    import httpx
    from attocode_intel.confidence.redact import redact

    body = "\n\n".join(f"[{i}]\n{redact(text)}" for i, text in enumerate(excerpts))
    user = f"Query:\n{redact(query)}\n\nCandidates:\n\n{body}\n\n{LISTWISE_END.format(count=len(excerpts))}"
    payload = {"model": model, "temperature": 0, "max_tokens": 512, "usage": {"include": True},
               "messages": [{"role": "system", "content": LISTWISE}, {"role": "user", "content": user},
                            {"role": "assistant", "content": "["}]}  # the answer starts as an array
    started = time.perf_counter()
    try:
        response = httpx.post(f"{OPENROUTER}/chat/completions", json=payload, timeout=120,
                              headers={"Authorization": f"Bearer {openrouter_key()}"})
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        text = text if text.lstrip().startswith("[") else "[" + text
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        return _done("request_failed", started, error=f"{type(error).__name__}: {error}"[:300])
    usage = data.get("usage") or {}
    cost = usage.get("cost")
    extra = {"cost_usd": float(cost) if isinstance(cost, int | float) else None,
             "tokens": [usage.get("prompt_tokens"), usage.get("completion_tokens")]}
    order = index_list(text, len(excerpts))
    if order is None:
        return _done("invalid_output", started, error=text[:300], **extra)
    return _done("ok", started, order, **extra)


def systemone(ranker, query: str, excerpts: list[str]) -> dict:
    """The production SystemOne adapter on the same evidence."""
    candidates = [(str(i), text, float(len(excerpts) - i)) for i, text in enumerate(excerpts)]
    with ranker._inflight:  # wait out an earlier timed-out call; one request at a time
        pass
    started = time.perf_counter()
    outcome = ranker.rerank_result(query, candidates, top_k=len(candidates))
    if not outcome.reranked:
        return _done("request_failed", started, error=outcome.fallback_reason)
    scores = {candidate: score for candidate, _text, score in outcome.candidates}
    return _ranked([scores[str(i)] for i in range(len(excerpts))], started)


def check_cross(arm: str, *, allow_remote_code: bool) -> None:
    """Stop before any work when a local model cannot load here."""
    from sentence_transformers import __version__

    spec = ARMS[arm]
    if spec.get("remote_code") and not allow_remote_code:
        raise SystemExit(f"{arm} runs model code from Hugging Face (revision {spec['revision']}). "
                         "Pass --allow-remote-code to run it.")
    if tuple(int(part) for part in __version__.split(".")[:2]) < spec.get("min_st", (0, 0)):
        raise SystemExit(f"{arm} needs sentence-transformers {'.'.join(map(str, spec['min_st']))} or later. "
                         f"This environment has {__version__}.")


def load_cross(arm: str):
    import torch
    from sentence_transformers import CrossEncoder

    spec = ARMS[arm]
    return CrossEncoder(spec["model"], revision=spec["revision"], max_length=MAX_LENGTH,
                        device="mps" if torch.backends.mps.is_available() else None,
                        trust_remote_code=bool(spec.get("remote_code")))


def cross_scores(model, arm: str, query: str, excerpts: list[str]) -> list[float]:
    spec = ARMS[arm]
    if spec.get("template") == "qwen3":
        head = f"{QWEN_PREFIX}<Instruct>: {INSTRUCTION}\n<Query>: {query}\n"
        pairs = [(head, f"<Document>: {text}{QWEN_SUFFIX}") for text in excerpts]
    else:
        pairs = [(query, text) for text in excerpts]
    return [float(s) for s in model.predict(pairs, batch_size=spec["batch"], show_progress_bar=False)]


def legacy_outputs(trial: dict) -> list[tuple[str, dict]]:
    """(cache key, output) for each case of an old jev-choice trial, so that a replay costs nothing."""
    if trial.get("model") != "jev-choice":
        return []
    chars = trial.get("max_query_chars") or 0
    found = []
    for case in trial["cases"]:
        if "scores" not in case or not case.get("evidence_sha256"):
            continue
        page, failed = case["baseline_files"], case.get("failures", 0) > 0
        output = {"status": "request_failed" if failed else "ok",
                  "order": None if failed else [page.index(path) for path in case["ranked_files"]],
                  "scores": case["scores"], "error": case.get("fallback_reason"), "ms": case.get("inference_ms"),
                  "cost_usd": JEV_USD_PER_CALL, "cost_source": "estimate", "source": "legacy trial"}
        query = case["query"][:chars] if chars else case["query"]
        found.append((listwise_key("jev-choice", JEV_MODEL, 1, query, case["evidence_sha256"], 0), output))
    return found


def _call(cache: Cache, budget: Budget, job: Job, estimate: float, ranker=None) -> None:
    spec = ARMS[job.arm]
    if spec["kind"] == "jev":
        def ask():
            return jev_choice(job.query, job.excerpts)
    elif spec["kind"] == "listwise":
        def ask():
            return listwise(spec["model"], job.query, job.excerpts)
    else:
        def ask():
            return systemone(ranker, job.query, job.excerpts)
    output = budget.call(job.arm, job.key, len(job.paths), estimate, ask) if spec.get("paid") else ask()
    if output is not None:
        cache.put(job.key, job.arm, output)
        job.output = output


def _estimate(cache: Cache, budget: Budget, arm: str, jobs: list[Job]) -> float:
    """The cost of the arm's open jobs. An arm without a measured cost first runs PROBE_CALLS of them."""
    if ARMS[arm]["kind"] == "jev":
        return JEV_USD_PER_CALL * len(jobs)
    if cache.unit_cost(arm) is None:
        for job in jobs[:PROBE_CALLS]:
            _call(cache, budget, job, PROBE_USD)
        if cache.unit_cost(arm) is None:
            raise SystemExit(f"refused: no measured cost for {arm} after {PROBE_CALLS} probe calls"
                             + (", because the cap stopped them" if budget.stopped.is_set() else ""))
    return cache.unit_cost(arm) * sum(len(job.paths) for job in jobs if job.output is None)


def execute(cache: Cache, budget: Budget, jobs: list[Job], *, retry_failed: bool = False,
            allow_remote_code: bool = False) -> Counter:
    """Fill job.output from the cache or the arm. Paid arms first get an estimate, and the run stops
    when the estimates pass the cap. Arms run in config order. Returns the status counts."""
    for job in jobs:
        if job.output is None and (ARMS[job.arm]["kind"] == "none" or len(job.paths) < 2):
            job.output = {"status": "ok", "order": list(range(len(job.paths))), "error": None, "ms": 0.0,
                          "cost_usd": 0.0}
        elif job.output is None and ARMS[job.arm]["kind"] != "cross":
            found = cache.get(job.key)
            if found is not None and not (retry_failed and found["status"] != "ok"):
                job.output, job.cache_hit = found, True
    arms = list(dict.fromkeys(job.arm for job in jobs))
    todo = {arm: [job for job in jobs if job.arm == arm and job.output is None] for arm in arms}
    for arm in arms:
        if todo[arm] and ARMS[arm]["kind"] == "cross":
            check_cross(arm, allow_remote_code=allow_remote_code)
    unique = {arm: list({job.key: job for job in todo[arm]}.values()) for arm in arms}  # one call per key
    estimates = {arm: _estimate(cache, budget, arm, unique[arm]) for arm in arms
                 if unique[arm] and ARMS[arm].get("paid")}
    spent = cache.spent(budget.run)
    if estimates and spent + sum(estimates.values()) > budget.cap + 1e-9:
        raise SystemExit(f"refused: ${spent:.4f} spent, and the estimates " + ", ".join(
            f"{arm} ${cost:.4f} ({sum(job.output is None for job in unique[arm])} calls)"
            for arm, cost in estimates.items()) + f" pass the cap of ${budget.cap:.4f}. Raise --budget-usd, "
            "or run fewer rerank entries.")
    for arm in arms:
        if not todo[arm]:
            continue
        started, spec = time.time(), ARMS[arm]
        if spec["kind"] == "cross":
            _run_cross(cache, arm, todo[arm])
        else:
            ranker = _ranker(todo[arm][0].entry) if spec["kind"] == "http" else None
            unit = cache.unit_cost(arm) or 0.0

            def one(job: Job, ranker=ranker, unit=unit, kind=spec["kind"]) -> None:
                if job.output is None:  # a probe call made it already
                    estimate = JEV_USD_PER_CALL if kind == "jev" else unit * len(job.paths) * MARGIN
                    _call(cache, budget, job, estimate, ranker)

            with ThreadPoolExecutor(max_workers=1 if ranker else WORKERS) as pool:
                list(pool.map(one, unique[arm]))
            made = {job.key: job.output for job in unique[arm]}
            for job in todo[arm]:
                if job.output is None and made.get(job.key) is not None:
                    job.output, job.cache_hit = made[job.key], True  # the same request as an earlier job
        left = sum(job.output is None for job in todo[arm])
        print(f"{arm}: {len(todo[arm]) - left} outputs made in {time.time() - started:.0f} s"
              + (f"; the cap stopped {left} jobs" if left else ""), flush=True)
    if budget.started:
        budget.check()
    return Counter(job.output["status"] if job.output else "stopped by the cap" for job in jobs)


def _ranker(entry: dict):
    from attocode_intel._internal.integrations.context.systemone_ranker import (
        SystemOneChoiceReranker,
    )

    timeout = entry.get("timeout_ms", 0)
    return SystemOneChoiceReranker(entry["endpoint"], model=entry.get("model_id", ""),
                                   auth_env=entry.get("auth_env", ""), allow_remote=remote("systemone-http", entry),
                                   max_candidates=max(entry["pages"]),
                                   timeout_seconds=timeout / 1000 if timeout else None)


def _run_cross(cache: Cache, arm: str, jobs: list[Job]) -> None:
    """Score each distinct (query, excerpt) once, with one model in memory."""
    rev, prompt = revision(arm, {}), ARMS[arm].get("prompt", 1)
    scores: dict[str, tuple[float, float]] = {}  # key -> (score, ms)
    todo: dict[str, dict[str, str]] = {}  # query -> key -> excerpt
    for job in jobs:
        for text in job.excerpts:
            key = pointwise_key(arm, rev, prompt, job.query, text)
            found = None if key in scores else cache.get(key)
            if found is not None:
                scores[key] = found["score"], found["ms"]
            elif key not in scores:
                todo.setdefault(job.query, {})[key] = text
    if todo:
        import gc

        import torch
        model = load_cross(arm)
        try:
            for query, items in todo.items():
                started = time.perf_counter()
                values = cross_scores(model, arm, query, list(items.values()))
                ms = round((time.perf_counter() - started) * 1000 / len(items), 1)
                for key, value in zip(items, values, strict=True):
                    cache.put(key, arm, {"score": value, "ms": ms})
                    scores[key] = value, ms
        finally:
            del model
            gc.collect()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
    fresh = {key for items in todo.values() for key in items}
    for job in jobs:
        keys = [pointwise_key(arm, rev, prompt, job.query, text) for text in job.excerpts]
        job.output = _ranked([scores[key][0] for key in keys], time.perf_counter(), cost_usd=0.0)
        job.output["ms"] = round(sum(scores[key][1] for key in keys), 1)
        job.cache_hit = not fresh.intersection(keys)
