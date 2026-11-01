"""Stage 1 screen of hosted code embeddings on 50 Loc-Bench tasks.

The design ``packages/code-intel/evals/designs/2026-11-hosted-embed-screen.json`` freezes the tasks,
the request, the spend limits and the gates. Steps (GitHub Actions only):

  python -m eval.matrix.embed_screen prepare --design D --work W   # needs pyarrow
  python -m eval.matrix.embed_screen run --design D --work W --model voyageai/voyage-code-4
  python -m eval.matrix.embed_screen decide --design D --work W

``prepare`` reads the pinned parquet, checks each task (query, gold), takes a snapshot of each commit
and checks its tree and function units. ``run`` embeds the units and queries with one OpenRouter
model, ranks the units of each task by cosine, and fuses the files with the product list. ``decide``
reads only the rows. The OpenRouter key comes from ``OPENROUTER_API_KEY`` and is never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

from eval.matrix.arms import rrf
from eval.matrix.function_dense import acc, files_of, ours

DOCS = [
    "def add(a, b):\n    return a + b\n",
    "class Stack:\n    def push(self, item):\n        self.items.append(item)\n",
]
QUERY = "Adding two numbers returns the wrong total."
_DATE = re.compile(r"-(\d{4}|\d{8}|\d{4}-\d{2}(-\d{2})?)$")


class SplitError(Exception):
    """The provider refused the request size (400 or 413)."""


class FailedError(Exception):
    """A request that did not give vectors."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def units_digest(docs: dict[str, str]) -> str:
    return _sha(json.dumps(sorted(docs.items())))


def same_model(want: str, got: object) -> bool:
    """The returned model is the pinned one; a provider prefix and a date suffix may differ."""

    def base(name: str) -> str:
        return _DATE.sub("", name.rsplit("/", 1)[-1])

    return isinstance(got, str) and base(got) == base(want)


def batches(texts: list[str], max_inputs: int, max_chars: int) -> list[list[str]]:
    out: list[list[str]] = []
    for text in texts:
        if out and len(out[-1]) < max_inputs and sum(map(len, out[-1])) + len(text) <= max_chars:
            out[-1].append(text)
        else:
            out.append([text])
    return out


def sign_p(wins: int, losses: int) -> float:
    """One-sided exact sign test: P(at least ``wins`` of the discordant tasks favor the candidate)."""
    n = wins + losses
    return 1.0 if n == 0 else sum(math.comb(n, i) for i in range(wins, n + 1)) / 2**n


class Embedder:
    """Bounded OpenRouter embedding calls with a spend limit. One instance per model."""

    def __init__(
        self, design: dict, model: dict, key: str, client: httpx.Client | None = None
    ) -> None:
        req = design["request"]
        self.endpoint, self.model, self.req = req["endpoint"], model["id"], req
        self.price, self.cap = model["usd_per_mtok"], model["spend_limit_usd"]
        self.key = key
        self.client = client or httpx.Client(
            timeout=req["timeout_seconds"], trust_env=False, follow_redirects=False
        )
        self.variant = req["preflight_variants"][0]
        self.dims: int | None = None
        self.lock = threading.Lock()
        self.spent = self.tokens = 0.0
        self.requests = self.retries = self.splits = 0
        self.abort: str | None = None
        self.sleep = time.sleep

    def body(self, texts: list[str], input_type: str) -> dict:
        body: dict = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.variant["input_type"]:
            body["input_type"] = input_type
        if self.variant["deny_data_collection"]:
            body["provider"] = {"data_collection": "deny"}
        return body

    def _vectors(self, data: dict, n: int) -> tuple[np.ndarray, float, float]:
        items = data.get("data")
        if (
            not same_model(self.model, data.get("model"))
            or not isinstance(items, list)
            or len(items) != n
        ):
            raise ValueError("wrong model or count")
        items = sorted(items, key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(n)):
            raise ValueError("wrong indexes")
        vecs = np.asarray([item["embedding"] for item in items], dtype=np.float32)
        if (
            vecs.ndim != 2
            or (self.dims is not None and vecs.shape[1] != self.dims)
            or not np.isfinite(vecs).all()
        ):
            raise ValueError("wrong vectors")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError("zero vector")
        usage = data.get("usage") or {}
        tokens = float(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        cost = usage.get("cost")
        cost = float(cost) if isinstance(cost, (int, float)) else tokens * self.price / 1e6
        return vecs / norms, tokens, cost

    def call(self, texts: list[str], input_type: str) -> np.ndarray:
        """One request with retries. Raises SplitError on 400/413, FailedError otherwise."""
        last = "no attempt"
        attempts, backoff = self.req["retry"]["attempts"], self.req["retry"]["backoff_seconds"]
        for attempt in range(attempts):
            with self.lock:
                if self.abort is None and self.spent >= self.cap:
                    self.abort = f"spend limit {self.cap}"
                if self.abort:
                    raise FailedError(self.abort)
                self.requests += 1
                self.retries += attempt > 0
            status: int | str
            data = None
            try:
                response = self.client.post(
                    self.endpoint,
                    json=self.body(texts, input_type),
                    headers={"Authorization": f"Bearer {self.key}"},
                )
                status = response.status_code
                if status == 200:
                    data = response.json()
            except (httpx.TimeoutException, httpx.TransportError) as error:
                status = "transport"
                last = type(error).__name__
            except ValueError:
                status = "invalid response"
            if status == 200 and isinstance(data, dict) and isinstance(data.get("error"), dict):
                status = data["error"].get("code", "invalid response")
            if status == 200:
                try:
                    vecs, tokens, cost = self._vectors(data, len(texts))
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    status = "invalid response"
                    last = str(error)
                else:
                    with self.lock:
                        self.dims = self.dims or vecs.shape[1]
                        self.tokens += tokens
                        self.spent += cost
                    return vecs
            if status in (400, 413):
                raise SplitError(str(status))
            if not (
                status in ("transport", "invalid response", 408, 429)
                or (isinstance(status, int) and status >= 500)
            ):
                with self.lock:
                    self.abort = self.abort or f"status {status}"
                raise FailedError(f"status {status}")
            last = f"status {status} {last}" if status == "transport" else f"status {status}"
            if attempt < attempts - 1:
                self.sleep(backoff[min(attempt, len(backoff) - 1)])
        raise FailedError(last)

    def embed(self, texts: list[str], input_type: str) -> dict[str, np.ndarray | None]:
        """Vectors by text; a text that the provider refuses alone maps to None."""
        try:
            return dict(zip(texts, self.call(texts, input_type), strict=True))
        except SplitError:
            if len(texts) == 1:
                return {texts[0]: None}
            with self.lock:
                self.splits += 1
            half = len(texts) // 2
            return {**self.embed(texts[:half], input_type), **self.embed(texts[half:], input_type)}
        except FailedError:
            return dict.fromkeys(texts)

    def preflight(self) -> list[dict]:
        """Use the first request variant that gives document and query vectors of one size."""
        tried = []
        for variant in self.req["preflight_variants"]:
            self.variant, self.dims = variant, None
            try:
                docs, query = self.call(DOCS, "search_document"), self.call([QUERY], "search_query")
            except (SplitError, FailedError) as error:
                tried.append({**variant, "result": str(error) or "refused"})
                with self.lock:
                    self.abort = (
                        None if not str(self.abort or "").startswith("spend") else self.abort
                    )
                continue
            if docs.shape[1] != query.shape[1]:
                raise SystemExit("preflight: document and query vectors differ in size")
            tried.append({**variant, "result": "ok", "dims": int(docs.shape[1])})
            return tried
        raise SystemExit(f"preflight: no request variant worked: {tried}")


def _load(design_path: Path) -> dict:
    return json.loads(design_path.read_text())


def _inst(task: dict) -> dict:
    return {
        "id": f"locbench/{task['id']}",
        "repo": task["repo"],
        "base_commit": task["base_commit"],
    }


def prepare(design: dict, work: Path) -> None:
    from eval.matrix import datasets, run

    data = design["dataset"]
    insts = datasets.load(
        "locbench", {k: data[k] for k in ("hf", "revision", "files")}, work / "data"
    )
    byid = {inst.id.split("/", 1)[1]: inst for inst in insts}
    ids = sorted(byid)
    if len(ids) != data["population"] or _sha("\n".join(ids)) != data["population_sha256"]:
        raise SystemExit("prepare: the dataset differs from the design")
    if sorted(random.Random(data["seed"]).sample(ids, data["size"])) != [
        t["id"] for t in design["tasks"]
    ]:
        raise SystemExit("prepare: the seeded sample differs from the design")
    for task in design["tasks"]:
        inst = byid[task["id"]]
        if (inst.repo, inst.base_commit, inst.gold, _sha(inst.queries["full"])) != (
            task["repo"],
            task["base_commit"],
            task["gold"],
            task["query_sha256"],
        ):
            raise SystemExit(f"prepare: task {task['id']} differs from the design")
    cache = work / "cache"
    run.MIN_FREE = (
        2 * 2**30
    )  # ponytail: a CI runner, not the shared Mac cache; 50 snapshots need about 5 GiB
    run.snapshot(cache, [byid[t["id"]] for t in design["tasks"]], sources=())
    unavailable = {}
    for task in design["tasks"]:
        tree = json.loads(run._tree_file(cache, task["repo"], task["base_commit"]).read_text())
        if "error" in tree:
            unavailable[task["id"]] = tree["error"]
            continue
        docs = ours((cache, _inst(task)))
        if (
            tree["tree"] != task["tree"]
            or len(docs) != task["units"]
            or units_digest(docs) != task["units_sha256"]
        ):
            raise SystemExit(
                f"prepare: the snapshot or units of {task['id']} differ from the design"
            )
    (work / "queries.json").write_text(
        json.dumps({t["id"]: byid[t["id"]].queries["full"] for t in design["tasks"]})
    )
    (work / "prepared.json").write_text(json.dumps({"unavailable": unavailable}, indent=1))
    print(
        f"prepared {len(design['tasks']) - len(unavailable)} of {len(design['tasks'])} tasks; "
        f"unavailable: {unavailable}",
        flush=True,
    )


def slug(model: str) -> str:
    return model.replace("/", "__")


def run_model(design: dict, work: Path, model_id: str, embedder: Embedder | None = None) -> dict:
    model = next(m for m in design["models"] if m["id"] == model_id)
    cap, req = design["text_cap_chars"], design["request"]
    if embedder is None:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise SystemExit("run: OPENROUTER_API_KEY is not set")
        embedder = Embedder(design, model, key)
    queries = json.loads((work / "queries.json").read_text())
    unavailable = json.loads((work / "prepared.json").read_text())["unavailable"]
    started = time.time()
    preflight = embedder.preflight()
    print(f"{model_id}: preflight {preflight}", flush=True)

    keys: dict[str, list[str]] = {}  # unit ids per task, in the order of ours()
    unit_texts: dict[str, list[str]] = {}  # capped unit texts per task, same order
    qtexts: dict[str, str] = {}
    texts: dict[str, None] = {}  # unique capped texts, in task order
    for task in design["tasks"]:
        tid = task["id"]
        if tid in unavailable:
            continue
        docs = ours((work / "cache", _inst(task)))
        if units_digest(docs) != task["units_sha256"] or _sha(queries[tid]) != task["query_sha256"]:
            raise SystemExit(f"run: the units or query of {tid} differ from the design")
        keys[tid], unit_texts[tid] = list(docs), [text[:cap] for text in docs.values()]
        qtexts[tid] = queries[tid][:cap]
        texts.update(dict.fromkeys(unit_texts[tid]))

    vecs: dict[str, np.ndarray | None] = {}
    size = req["batch"]["max_inputs"], req["batch"]["max_chars"]
    vecs_q: dict[str, np.ndarray | None] = {}
    for part in batches(list(dict.fromkeys(qtexts.values())), *size):
        vecs_q.update(embedder.embed(part, "search_query"))
    work_batches = batches(list(texts), *size)
    print(f"{model_id}: {len(texts)} units in {len(work_batches)} requests", flush=True)
    with ThreadPoolExecutor(req["workers"]) as pool:
        for n, part in enumerate(
            pool.map(lambda b: embedder.embed(b, "search_document"), work_batches), 1
        ):
            vecs.update(part)
            if n % 250 == 0 or n == len(work_batches):
                print(
                    f"{model_id}: {n}/{len(work_batches)} requests, ${embedder.spent:.3f}, "
                    f"{time.time() - started:.0f} s",
                    flush=True,
                )

    rows = []
    for task in design["tasks"]:
        tid, row = task["id"], {"model": model_id, "id": tid}
        if tid in unavailable:
            rows.append({**row, "status": "unavailable", "reason": unavailable[tid]})
            continue
        q = vecs_q.get(qtexts[tid])
        missing = sum(vecs.get(text) is None for text in unit_texts[tid])
        if q is None or missing:
            rows.append(
                {**row, "status": "incomplete", "missing_units": missing, "query": q is not None}
            )
            continue
        scores = np.stack([vecs[text] for text in unit_texts[tid]]) @ q
        ranked = [keys[tid][i] for i in np.argsort(-scores, kind="stable")]
        files = files_of(ranked)[:200]
        fused = rrf([task["product"], files])
        rows.append(
            {
                **row,
                "status": "ok",
                "units": len(keys[tid]),
                "files": files[:48],
                "rrf": fused[:48],
                "acc5_model": acc(files, task["gold"], 5),
                "acc5_rrf": acc(fused, task["gold"], 5),
            }
        )
    summary = {
        "model": model_id,
        "preflight": preflight,
        "variant": embedder.variant,
        "dims": embedder.dims,
        "unique_units": len(texts),
        "requests": embedder.requests,
        "retries": embedder.retries,
        "splits": embedder.splits,
        "refused_inputs": sum(v is None for v in vecs.values()),
        "spent_usd": round(embedder.spent, 6),
        "tokens": embedder.tokens,
        "abort": embedder.abort,
        "seconds": round(time.time() - started, 1),
        "ok": sum(r["status"] == "ok" for r in rows),
    }
    (work / f"rows-{slug(model_id)}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (work / f"summary-{slug(model_id)}.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


def decide(design: dict, work: Path) -> dict:
    """The frozen gates, from the rows only."""
    tasks = {t["id"]: t for t in design["tasks"]}
    product = design["reference"]["hits5"]["product"]
    models = {}
    for model in design["models"]:
        path = work / f"rows-{slug(model['id'])}.jsonl"
        if not path.exists():
            models[model["id"]] = {"verdict": "not run"}
            continue
        rows = {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}
        ok = {tid: r for tid, r in rows.items() if r["status"] == "ok"}
        fused = {tid: bool(ok.get(tid, {}).get("acc5_rrf")) for tid in tasks}
        wins = sum(fused[t] and not tasks[t]["acc5"]["product"] for t in tasks)
        losses = sum(tasks[t]["acc5"]["product"] and not fused[t] for t in tasks)
        hits = {
            "rrf": sum(fused.values()),
            "model": sum(bool(r["acc5_model"]) for r in ok.values()),
        }
        summary_path = work / f"summary-{slug(model['id'])}.json"
        spent = json.loads(summary_path.read_text())["spent_usd"] if summary_path.exists() else None
        out = {
            "ok": len(ok),
            "incomplete": len(tasks) - len(ok),
            "hits5": hits,
            "product_hits5": product,
            "net": hits["rrf"] - product,
            "wins": wins,
            "losses": losses,
            "sign_p": round(sign_p(wins, losses), 6),
            "spent_usd": spent,
        }
        if out["incomplete"] > 2:
            out["verdict"] = "incomplete"
        else:
            out["verdict"] = "pass" if out["net"] >= 5 and out["sign_p"] <= 0.05 else "fail"
        models[model["id"]] = out
    passing = [m for m, r in models.items() if r["verdict"] == "pass"]
    winner = min(
        passing,
        key=lambda m: (
            -models[m]["hits5"]["rrf"],
            -models[m]["hits5"]["model"],
            models[m]["spent_usd"] or 0.0,
        ),
        default=None,
    )
    return {
        "design": design["name"],
        "reference_hits5": design["reference"]["hits5"],
        "models": models,
        "winner": winner,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=["prepare", "run", "decide"])
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    design = _load(args.design)
    args.work.mkdir(parents=True, exist_ok=True)
    if args.step == "prepare":
        prepare(design, args.work)
    elif args.step == "run":
        if not args.model:
            raise SystemExit("run needs --model")
        summary = run_model(design, args.work, args.model)
        if summary["ok"] == 0:
            sys.exit(1)
    else:
        decision = decide(design, args.work)
        (args.work / "decision.json").write_text(
            json.dumps(decision, indent=1, sort_keys=True) + "\n"
        )
        print(json.dumps(decision, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
