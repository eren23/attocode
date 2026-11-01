import json

import httpx
import numpy as np
import pytest

from eval.matrix import embed_screen as es

MODEL = "voyageai/voyage-code-4"


def design(tasks=(), cap=1.0):
    return {
        "name": "t",
        "text_cap_chars": 100,
        "request": {
            "endpoint": "https://openrouter.ai/api/v1/embeddings",
            "preflight_variants": [
                {"input_type": True, "deny_data_collection": True},
                {"input_type": False, "deny_data_collection": True},
            ],
            "batch": {"max_inputs": 2, "max_chars": 1000},
            "retry": {"attempts": 3, "backoff_seconds": [0, 0]},
            "workers": 2,
            "timeout_seconds": 5,
        },
        "models": [{"id": MODEL, "usd_per_mtok": 0.12, "spend_limit_usd": cap}],
        "reference": {"hits5": {"product": 1}},
        "tasks": list(tasks),
    }


def vector(text):
    return [float("login" in text), float("cache" in text), 0.1]


def ok(request, model="voyage-code-4-20261001", cost=0.001):
    texts = json.loads(request.content)["input"]
    data = [{"index": i, "embedding": vector(t)} for i, t in reversed(list(enumerate(texts)))]
    return httpx.Response(
        200, json={"model": model, "data": data, "usage": {"prompt_tokens": 10, "cost": cost}}
    )


def embedder(handler, cap=1.0):
    emb = es.Embedder(
        design(cap=cap),
        design(cap=cap)["models"][0],
        "k",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    emb.sleep = lambda _: None
    return emb


def test_helpers():
    assert es.same_model(MODEL, "voyage-code-4-20261001")
    assert es.same_model("mistralai/codestral-embed-2505", "codestral-embed")
    assert not es.same_model(MODEL, "voyage-3")
    assert es.batches(["a" * 10, "b", "c", "d" * 1000], 2, 1000) == [
        ["a" * 10, "b"],
        ["c"],
        ["d" * 1000],
    ]
    assert es.sign_p(0, 0) == 1.0
    assert es.sign_p(5, 0) == pytest.approx(1 / 32)
    assert es.sign_p(1, 1) == pytest.approx(0.75)


def test_call_orders_normalizes_and_counts_spend():
    emb = embedder(ok)
    vecs = emb.embed(["login a", "cache b"], "search_document")
    assert np.allclose(vecs["login a"], np.array([1, 0, 0.1]) / np.linalg.norm([1, 0, 0.1]))
    assert emb.spent == pytest.approx(0.001) and emb.tokens == 10 and emb.dims == 3


def test_body_follows_the_variant():
    emb = embedder(ok)
    assert emb.body(["x"], "search_query") == {
        "model": MODEL,
        "input": ["x"],
        "encoding_format": "float",
        "input_type": "search_query",
        "provider": {"data_collection": "deny"},
    }


def test_split_on_400_and_refuse_a_single_text():
    def handler(request):
        texts = json.loads(request.content)["input"]
        return httpx.Response(400) if "bad" in texts else ok(request)

    emb = embedder(handler)
    vecs = emb.embed(["login", "bad"], "search_document")
    assert vecs["bad"] is None and vecs["login"] is not None and emb.splits == 1


def test_retry_then_success_and_abort_on_401():
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else ok(request)

    emb = embedder(flaky)
    assert emb.embed(["login"], "search_document")["login"] is not None and emb.retries == 2

    emb = embedder(lambda request: httpx.Response(401))
    assert emb.embed(["login"], "search_document") == {"login": None}
    assert emb.abort == "status 401" and emb.requests == 1
    assert emb.embed(["cache"], "search_document") == {"cache": None} and emb.requests == 1


def test_wrong_model_is_an_invalid_response():
    emb = embedder(lambda request: ok(request, model="voyage-3"))
    assert emb.embed(["login"], "search_document") == {"login": None} and emb.requests == 3


def test_spend_limit_stops_requests():
    emb = embedder(lambda request: ok(request, cost=0.6), cap=1.0)
    for text in ("a", "b", "c"):
        emb.embed([text], "search_document")
    assert emb.requests == 2 and emb.abort == "spend limit 1.0"


def test_preflight_takes_the_first_working_variant():
    def handler(request):
        return httpx.Response(400) if "input_type" in json.loads(request.content) else ok(request)

    emb = embedder(handler)
    tried = emb.preflight()
    assert [t["result"] for t in tried] == ["400", "ok"] and emb.variant["input_type"] is False
    assert emb.abort is None

    with pytest.raises(SystemExit):
        embedder(lambda request: httpx.Response(403)).preflight()


def test_run_and_decide(tmp_path, monkeypatch):
    docs = {
        "t1": {"a.py/login": "def login(): pass", "b.py/cache": "def cache(): pass"},
        "t2": {"a.py/login": "def login(): pass", "c.py/other": "def other(): pass"},
    }
    queries = {"t1": "cache misses", "t2": "login fails"}
    tasks = [
        {
            "id": tid,
            "repo": "o/r",
            "base_commit": "c",
            "gold": gold,
            "query_sha256": es._sha(queries[tid]),
            "units_sha256": es.units_digest(docs[tid]),
            "product": ["x.py"],
            "acc5": {"product": tid == "t2"},
        }
        for tid, gold in (("t1", ["b.py"]), ("t2", ["a.py"]))
    ]
    monkeypatch.setattr(es, "ours", lambda arg: docs[arg[1]["id"].split("/", 1)[1]])
    (tmp_path / "queries.json").write_text(json.dumps(queries))
    (tmp_path / "prepared.json").write_text(json.dumps({"unavailable": {}}))
    d = design(tasks)
    summary = es.run_model(d, tmp_path, MODEL, embedder(ok))
    assert summary["ok"] == 2 and summary["unique_units"] == 3
    rows = [
        json.loads(line)
        for line in (tmp_path / f"rows-{es.slug(MODEL)}.jsonl").read_text().splitlines()
    ]
    assert [r["id"] for r in rows] == ["t1", "t2"]
    assert rows[0]["files"][0] == "b.py" and rows[0]["acc5_rrf"] and rows[1]["acc5_rrf"]

    decision = es.decide(d, tmp_path)["models"][MODEL]
    assert (
        decision["hits5"] == {"rrf": 2, "model": 2}
        and decision["wins"] == 1
        and decision["losses"] == 0
    )
    assert decision["net"] == 1 and decision["verdict"] == "fail"


def test_decide_counts_incomplete_tasks_as_misses(tmp_path):
    tasks = [{"id": f"t{i}", "acc5": {"product": False}} for i in range(10)]
    rows = [
        {"id": f"t{i}", "status": "ok", "acc5_rrf": True, "acc5_model": False} for i in range(7)
    ]
    rows += [{"id": f"t{i}", "status": "incomplete"} for i in range(7, 10)]
    (tmp_path / f"rows-{es.slug(MODEL)}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )
    d = design(tasks)
    d["reference"]["hits5"]["product"] = 0
    result = es.decide(d, tmp_path)
    assert result["models"][MODEL]["verdict"] == "incomplete" and result["winner"] is None

    rows[7] = {"id": "t7", "status": "ok", "acc5_rrf": True, "acc5_model": True}
    (tmp_path / f"rows-{es.slug(MODEL)}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )
    result = es.decide(d, tmp_path)
    assert result["models"][MODEL]["verdict"] == "pass" and result["winner"] == MODEL
