from attocode.tui.widgets._path_utils import short_path


def test_short_path_fits_unchanged():
    assert short_path("a/b/c.py", max_len=45) == "a/b/c.py"


def test_short_path_at_exact_limit():
    p = "x" * 45
    assert short_path(p, max_len=45) == p


def test_short_path_collapses_middle():
    p = "src/attocode/integrations/context/codebase_context.py"
    out = short_path(p, max_len=45)
    assert out.startswith("src/")
    assert "…" in out
    assert out.endswith("context/codebase_context.py")
    assert len(out) <= 45


def test_short_path_few_parts_returns_original():
    p = "very_long_filename_that_exceeds_max.py"
    assert short_path(p, max_len=20) == p


def test_short_path_fallback_truncation():
    p = "very_long_first_dir/middle1/middle2/very_long_last_dir/very_long_filename.py"
    out = short_path(p, max_len=20)
    assert len(out) == 20
    assert out.endswith("…")
