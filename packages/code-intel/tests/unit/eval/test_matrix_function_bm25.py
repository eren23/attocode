from collections import Counter

from eval.matrix import function_bm25 as fb


def test_bm25_ranks_by_score_and_drops_zero_scores():
    docs = [(10, Counter({"cache": 1})), (10, Counter()), (10, Counter({"cache": 3, "key": 1})), (40, Counter({"cache": 1}))]
    assert fb.bm25(docs, {"cache", "key"}, k1=2.2, b=0.3) == [2, 0, 3]  # doc 1 has no query term


def test_bm25_breaks_ties_by_index():
    docs = [(5, Counter({"x": 1})), (5, Counter({"x": 1}))]
    assert fb.bm25(docs, {"x"}, k1=1.2, b=0.75) == [0, 1]


def test_windows_cover_all_lines_with_the_path_first():
    source = "\n".join(f"line {i}" for i in range(85))
    out = fb.windows("pkg/a.py", source)
    assert len(out) == 3
    assert out[0].splitlines()[:2] == ["File: pkg/a.py", "line 0"]
    assert out[2].splitlines()[1:] == [f"line {i}" for i in range(80, 85)]
    assert fb.windows("pkg/empty.py", "") == ["File: pkg/empty.py\n"]
