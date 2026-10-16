"""Scoped auto-builds must not poison legacy tools or another workspace."""

import pytest
from attocode_intel.gateway import OperationGateway
from attocode_intel.tools import search_tools


@pytest.fixture(autouse=True)
def isolated_legacy_cache(monkeypatch):
    monkeypatch.setattr(search_tools, "_trigram_index", None)
    yield
    if search_tools._trigram_index is not None:
        search_tools._trigram_index.close()


async def test_scoped_auto_build_stays_owned_by_gateway_then_legacy_regex_finds_its_source(
    tmp_path, monkeypatch
):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.py").write_text("def quality_helper(): return 1\n")
    (second / "same.py").write_text("def greet(): return 'hello world'\n")
    gateway = OperationGateway(str(first), profile="full", watch=False)
    try:
        result = await gateway.execute("fast_search", {"pattern": "quality_helper"})
        assert "same.py" in result.content[0].text
        assert search_tools._trigram_index is None
        index = next(iter(gateway._stores.values()))["trigrams"]
        assert index.is_ready()
    finally:
        await gateway.close()
    assert not index.is_ready()
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(second))
    assert "same.py" in search_tools.regex_search("hello world")


async def test_two_gateway_workspaces_keep_auto_built_indices_separate(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.py").write_text("alpha_only\n")
    (second / "same.py").write_text("beta_only\n")
    gateway = OperationGateway(profile="full", watch=False)
    try:
        for root, pattern in [(first, "alpha_only"), (second, "beta_only")]:
            result = await gateway.execute(
                "fast_search", {"workspace": str(root), "pattern": pattern}
            )
            assert "same.py" in result.content[0].text
        a = await gateway.execute(
            "regex_search", {"workspace": str(first), "pattern": "alpha_only"}
        )
        b = await gateway.execute(
            "regex_search", {"workspace": str(second), "pattern": "beta_only"}
        )
        assert "same.py" in a.content[0].text and "alpha_only" in a.content[0].text
        assert "same.py" in b.content[0].text and "beta_only" in b.content[0].text
        indices = [store["trigrams"] for store in gateway._stores.values()]
        assert len(indices) == 2 and indices[0] is not indices[1]
        assert search_tools._trigram_index is None
    finally:
        await gateway.close()
    assert all(not index.is_ready() for index in indices)


def test_legacy_cache_switches_roots_and_closes_previous_index(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.py").write_text("alpha_only\n")
    (second / "same.py").write_text("beta_only\n")
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(first))
    assert "same.py" in search_tools.fast_search("alpha_only")
    index = search_tools._trigram_index
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(second))
    assert "same.py" in search_tools.regex_search("beta_only")
    assert search_tools._trigram_index is None
    assert not index.is_ready()
