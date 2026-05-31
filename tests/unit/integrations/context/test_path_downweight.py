"""Non-source paths (tests, benchmarks, docs) are down-weighted in ranking."""
from __future__ import annotations

from attocode.integrations.context.semantic_search import SemanticSearchManager


def test_test_path_penalty_is_below_one(tmp_path):
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    assert mgr._path_rank_penalty("src/attocode/foo.py") == 1.0
    assert mgr._path_rank_penalty("tests/unit/test_foo.py") < 1.0
    assert mgr._path_rank_penalty("asv_bench/benchmarks/x.py") < 1.0
    assert mgr._path_rank_penalty("docs_src/tutorial.py") < 1.0
