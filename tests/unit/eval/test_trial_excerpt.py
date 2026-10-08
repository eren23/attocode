from types import SimpleNamespace

from attocode_intel.service import CodeIntelService

from eval.model_rerank_trial import _excerpt


def test_trial_excerpt_matches_product_excerpt(tmp_path):
    # Line 1 matches only the excluded term; line 60 matches the task. The product
    # drops excluded terms, so a trial that keeps them shows the model other lines.
    lines = ["cache = {}"] + [f"x{n} = {n}" for n in range(58)] + ["def parse_header(): pass"]
    (tmp_path / "a.py").write_text("\n".join(lines))
    query = "parse header without cache"
    product = CodeIntelService._rerank_file_excerpt(
        SimpleNamespace(_project_dir=str(tmp_path)), SimpleNamespace(file_path="a.py"), query)
    assert _excerpt(tmp_path, "a.py", query) == product
    assert "1: cache" not in product
