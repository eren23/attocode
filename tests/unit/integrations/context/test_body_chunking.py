"""Body-aware chunking: _slice_body extracts token-budgeted symbol bodies."""
from __future__ import annotations

from attocode.integrations.context.semantic_search import SemanticSearchManager


def _mgr(tmp_path):
    return SemanticSearchManager(root_dir=str(tmp_path))


def test_slice_body_returns_body_within_budget(tmp_path):
    lines = [
        "def f(x):",            # line 1 (start_line)
        "    total = 0",        # 2
        "    for i in x:",      # 3
        "        total += i",   # 4
        "    return total",     # 5
    ]
    mgr = _mgr(tmp_path)
    out = mgr._slice_body(lines, start_line=1, end_line=5, max_tokens=1000)
    assert "total = 0" in out
    assert "return total" in out


def test_slice_body_trims_to_token_budget(tmp_path):
    lines = ["def f():"] + [f"    x{i} = {i}" for i in range(500)]
    mgr = _mgr(tmp_path)
    out = mgr._slice_body(lines, start_line=1, end_line=len(lines), max_tokens=20)
    from attocode.integrations.utilities.token_estimate import estimate_tokens
    assert estimate_tokens(out) <= 60
    assert "x0 = 0" in out  # head of body is kept


def test_slice_body_clamps_end_past_eof(tmp_path):
    lines = ["def f():", "    return 1"]
    mgr = _mgr(tmp_path)
    out = mgr._slice_body(lines, start_line=1, end_line=999, max_tokens=1000)
    assert "return 1" in out


def test_slice_body_empty_when_no_body(tmp_path):
    lines = ["def f(): ..."]
    mgr = _mgr(tmp_path)
    out = mgr._slice_body(lines, start_line=1, end_line=1, max_tokens=1000)
    assert out == ""
