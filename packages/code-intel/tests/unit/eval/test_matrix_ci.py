import json

import pytest
import yaml

from eval.matrix import arms, ci
from eval.matrix.datasets import Instance

INSTS = [Instance(id=f"pack/{name}", repo="o/r", base_commit="c", language="", category="", created_at="",
                  queries={"full": name}, gold=[f"{name}.py"], grades=None) for name in "abc"]
BASE = {"rows": {"pack/a|full|product": ["a.py", "x.py"], "pack/b|full|product": ["b.py"],
                 "pack/c|full|product": ["x.py"]}}


def _gate(files: dict[str, list[str]], status: str = "ok", net_loss: int = 2, mrr5_drop: float = 1.0):
    now = {f"pack/{name}|full|product": {"status": status, "files": ranked} for name, ranked in files.items()}
    return ci.compare(INSTS, BASE, now, ["product"], net_loss, mrr5_drop)


def test_same_files_pass():
    lines, failed = _gate({"a": ["a.py", "x.py"], "b": ["b.py"], "c": ["x.py"]}, mrr5_drop=0.01)
    assert not failed and "0 queries changed their first five files." in lines


def test_two_net_losses_fail_and_one_does_not():
    assert _gate({"a": ["x.py"], "b": ["x.py"], "c": ["x.py"]})[1]
    lines, failed = _gate({"a": ["x.py"], "b": ["b.py"], "c": ["c.py"]})
    assert not failed and "2 queries changed their first five files:" in lines  # one loss, one gain


def test_an_mrr_drop_fails_without_a_lost_hit():
    lines, failed = _gate({"a": ["x.py", "a.py"], "b": ["b.py"], "c": ["x.py"]}, mrr5_drop=0.01)
    assert failed and "| product | 3 | 0 | 0 | 0 | 0 | 0.667 | 0.500 | FAIL |" in lines


def test_a_failed_result_or_another_query_set_fails():
    assert _gate({"a": [], "b": ["b.py"], "c": ["x.py"]}, status="index_failed")[1]
    assert _gate({"a": ["a.py", "x.py"], "b": ["b.py"]})[1]


def test_ci_set_is_public_github_text_with_known_cells():
    cfg = yaml.safe_load(ci.CONFIG.read_text())
    assert set(cfg["cells"]) <= set(arms.CELLS)
    insts = ci.instances()
    assert len(insts) == len({inst.id for inst in insts}) and all(inst.gold for inst in insts)
    assert all("/" in inst.repo and len(inst.base_commit) == 40 for inst in insts)  # the gate fetches from GitHub
    assert {inst.dataset for inst in insts} == {"broad_dev", "mcp_bench", "locbench"}


@pytest.mark.skipif(not ci.BASELINE.exists(), reason="no committed baseline")
def test_baseline_covers_the_ci_set():
    cfg, rows = yaml.safe_load(ci.CONFIG.read_text()), json.loads(ci.BASELINE.read_text())["rows"]
    expected = {f"{inst.id}|{variant}|{cell}" for inst in ci.instances() for variant, query in inst.queries.items()
                if variant == next(v for v, q in inst.queries.items() if q == query) for cell in cfg["cells"]}
    assert set(rows) == expected
