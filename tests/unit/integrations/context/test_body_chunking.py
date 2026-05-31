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


import os


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_function_chunk_embeds_body_but_display_text_stays_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_BODY_TOKEN_BUDGET", "400")
    src = (
        "def authenticate(user, password):\n"
        '    """Check creds."""\n'
        "    salted = hash_password(password)\n"
        "    return salted == stored_hash\n"
    )
    _write(tmp_path, "auth.py", src)
    mgr = SemanticSearchManager(root_dir=str(tmp_path))

    chunks = mgr._chunk_single_file("auth.py", str(tmp_path / "auth.py"))
    func = next(c for c in chunks if c[0] == "func:auth.py:authenticate")
    display_text = func[3]

    # display/stored text stays the concise signature (no body)
    assert "salted" not in display_text

    # embedded text (what the model sees) DOES include the body
    embedded = mgr._get_embedding_texts([func])[0]
    assert "salted" in embedded


def test_body_budget_zero_disables_bodies(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_BODY_TOKEN_BUDGET", "0")
    src = "def f(x):\n    secret_token = 42\n    return secret_token\n"
    _write(tmp_path, "m.py", src)
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    func = next(c for c in mgr._chunk_single_file("m.py", str(tmp_path / "m.py"))
               if c[0].startswith("func:"))
    embedded = mgr._get_embedding_texts([func])[0]
    assert "secret_token" not in embedded
