"""Checks for the retrieval comparison in eval/jev_retrieval.py; no network, no Jev calls."""

from eval.jev_retrieval import jev_rerank, parse_jg


def test_parse_jg_reads_ranked_files_only():
    stdout = (
        "Summary: JSON responses are built in lib/response.js.\n"
        '- "lib/response.js" — implementation; caller\n'
        "  Reading lead json: lines 236-258\n"
        '- "test/res.json.js" — test\n'
        'Source block "lib/response.js" lines 236-258:\n'
    )
    assert parse_jg(stdout) == ["lib/response.js", "test/res.json.js"]


def test_rerank_orders_by_probability_and_keeps_rank_on_failure():
    probs = {"a.py": 0.1, "b.py": 0.9, "c.py": None}
    ranked, calls, failed = jev_rerank(
        "query", [("a.py", ""), ("b.py", ""), ("c.py", "")], "/repo",
        ask=lambda rank, path, text: probs[path],
    )
    # A failed answer counts as 0.5: below b (0.9), above a (0.1).
    assert ranked == ["b.py", "c.py", "a.py"] and (calls, failed) == (3, 1)
