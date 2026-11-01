"""The opt-in hosted embedding list: consent, spend guards, requests and fusion."""
import asyncio
import json
import os

import httpx
import pytest
from attocode_intel._internal.integrations.context.embeddings import (
    OpenRouterEmbeddingProvider,
    create_hosted_provider,
)
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.gateway import OperationGateway

MODEL = "voyage-code-4-20261001"


def vector(text):
    near = "zebra" in text or "striped" in text
    return [1.0 if near else 0.0, 0.0 if near else 1.0] + [0.0] * 1022


def reply(texts, model=MODEL):
    return {"model": model, "data": [{"index": i, "embedding": vector(t)} for i, t in reversed(list(enumerate(texts)))],
            "usage": {"prompt_tokens": len(texts), "cost": 0.001}}


def provider(handler):
    p = OpenRouterEmbeddingProvider(transport=httpx.MockTransport(handler))
    p.sleep = lambda _: None
    return p


@pytest.fixture
def consent(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_EMBEDDING", "openrouter")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE", "1")
    monkeypatch.setenv("ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE", str(tmp_path.resolve()))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
    return tmp_path


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def post(self, body):
        seen.append(body)
        if getattr(post, "fail", False):
            raise httpx.ConnectError("down")
        return reply(body["input"])

    monkeypatch.setattr(OpenRouterEmbeddingProvider, "_post", post)
    seen.post = post
    return seen


def write_repo(root):
    (root / "stable.py").write_text("def horse():\n    return 'stable horse'\n")
    (root / "animals.py").write_text("def zebra():\n    return 'black and white'\n")


def warm(manager):
    manager.search("warmup", top_k=24)
    assert manager.wait_for_body_index(timeout=10)


def files(results):
    return list(dict.fromkeys(r.file_path for r in results))


def test_request_body_batches_header_and_normalized_vectors(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=reply(json.loads(request.content)["input"]))

    p = provider(handler)
    vecs = p.embed([f"text {i}" for i in range(33)])
    bodies = sorted((json.loads(r.content) for r in seen), key=lambda b: -len(b["input"]))
    assert [len(b["input"]) for b in bodies] == [32, 1] and p.requests == 2
    assert {k: v for k, v in bodies[0].items() if k != "input"} == {
        "model": "voyageai/voyage-code-4", "encoding_format": "float",
        "input_type": "search_document", "provider": {"data_collection": "deny"}}
    assert seen[0].headers["authorization"] == "Bearer test"
    assert len(vecs) == 33 and all(len(v) == 1024 and v[1] == pytest.approx(1.0) for v in vecs)
    assert p.tokens == 33 and p.cost == pytest.approx(0.002)
    assert json.loads(seen[0].content)["input_type"] == "search_document"
    p.embed_query(["striped"])
    assert json.loads(seen[-1].content)["input_type"] == "search_query"


def test_retry_then_abort_on_401_with_no_later_request():
    count = []

    def flaky(request):
        count.append(1)
        return httpx.Response(429) if len(count) < 3 else httpx.Response(200, json=reply(["a"]))

    p = provider(flaky)
    assert p.embed(["a"])[0] and p.requests == 3

    p = provider(lambda request: httpx.Response(401))
    assert p.embed(["a"]) == [[]] and p.abort == "status 401" and p.requests == 1
    assert p.embed(["b", "c"]) == [[], []] and p.requests == 1


def test_wrong_model_fails_and_a_refused_input_is_split_out():
    p = provider(lambda request: httpx.Response(200, json=reply(json.loads(request.content)["input"], "voyage-3")))
    assert p.embed(["a"]) == [[]] and p.requests == 6
    assert p.embed_query(["a"]) == [[]] and p.requests == 8

    def handler(request):
        texts = json.loads(request.content)["input"]
        return httpx.Response(400) if "bad" in texts else httpx.Response(200, json=reply(texts))

    p = provider(handler)
    good, bad = p.embed(["good", "bad"])
    assert len(good) == 1024 and bad == [] and p.abort is None


@pytest.mark.parametrize("change", [
    {"ATTOCODE_INTEL_RANKING_ALLOW_REMOTE": None},
    {"ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE": "relative/path"},
    {"ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE": "/somewhere/else"},
    {"DATABASE_URL": "postgresql://x"},
    {"ATTOCODE_LOCAL_ONLY": "1"},
    {"OPENROUTER_API_KEY": None},
])
def test_each_consent_refusal(consent, monkeypatch, change):
    project = os.path.realpath(consent)
    assert create_hosted_provider("openrouter", project).remote
    for name, value in change.items():
        if value is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_hosted_provider("openrouter", project)


def test_unknown_kind_is_refused(consent):
    with pytest.raises(ValueError):
        create_hosted_provider("openai", os.path.realpath(consent))


def test_off_by_default_makes_no_request_and_no_store(tmp_path, monkeypatch, calls):
    monkeypatch.delenv("ATTOCODE_INTEL_EMBEDDING", raising=False)
    write_repo(tmp_path)
    manager = SemanticSearchManager(str(tmp_path))
    try:
        warm(manager)
        plain = manager.search_candidates("striped horse", 24, "")
        assert files(manager.search("striped horse", top_k=24)) == files(plain) == ["stable.py"]
        assert files(manager.search_candidates("striped horse", 24, "", dense_files=())) == files(plain)
        assert not calls and manager._dense_last == {}
        assert not (tmp_path / ".attocode" / "vectors" / "embeddings-openrouter.db").exists()
    finally:
        manager.close()


def test_refused_consent_stays_lexical_and_never_auto_detects(consent, monkeypatch, calls):
    monkeypatch.delenv("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE")
    write_repo(consent)
    manager = SemanticSearchManager(str(consent))
    try:
        warm(manager)
        assert files(manager.search("striped horse", top_k=24)) == ["stable.py"]
        assert manager._index_progress.degraded_reason == "hosted_embedding_refused"
        assert manager.index() == 0 and not calls and manager._dense_last["status"] == "off"
        assert manager.start_background_indexing().degraded_reason == "hosted_embedding_refused"
    finally:
        manager.close()


def test_only_an_explicit_index_spends_and_a_dense_only_file_enters(consent, calls):
    write_repo(consent)
    manager = SemanticSearchManager(str(consent))
    try:
        warm(manager)
        assert files(manager.search("striped horse", top_k=24)) == ["stable.py"]
        manager.queue_reindex(str(consent / "animals.py"))
        assert manager.reindex_file("animals.py") == 0 and not calls
        assert manager._dense_last["status"] == "off"

        assert manager.index() > 0 and calls and manager._store.count() > 0
        indexed = len(calls)
        # Equal RRF scores tie, and ties sort by path. stable.py has cosine 0, so
        # the vector search drops it; only animals.py is a dense file.
        assert set(files(manager.search("striped horse", top_k=24))) == {"stable.py", "animals.py"}
        assert len(calls) == indexed + 1 and calls[-1]["input_type"] == "search_query"
        assert manager._dense_last["status"] == "ok" and manager._dense_last["files"] == 1

        calls.post.fail = True
        manager._provider.sleep = lambda _: None
        assert files(manager.search("striped horse", top_k=24)) == ["stable.py"]
        assert manager._dense_last["status"] == "failed"
    finally:
        manager.close()


async def test_gateway_delivers_the_dense_file_with_its_source_lines(consent, calls):
    write_repo(consent)
    gateway = OperationGateway(str(consent), profile="daily", watch=False)
    try:
        await gateway.execute_mcp("semantic_search", {"query": "warmup", "top_k": 24})
        key = next(iter(gateway._stores))
        manager = gateway._stores[key]["service"]._get_semantic_search()
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(gateway._workers[key], lambda: manager.wait_for_body_index(timeout=10))
        assert not calls
        assert await loop.run_in_executor(gateway._workers[key], manager.index) > 0
        result = await gateway.execute_mcp("semantic_search", {"query": "striped horse", "top_k": 5})
        hits = json.loads(result.content[0].text)["data"]["results"]
        zebra = next(h for h in hits if h["file_path"] == "animals.py")
        assert zebra["line"] == 1 and zebra["end_line"] == 2
        assert "def zebra" in json.dumps(zebra)
        assert manager._dense_last["status"] == "ok"
    finally:
        await gateway.close()
