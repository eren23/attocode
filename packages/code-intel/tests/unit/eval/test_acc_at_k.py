from eval.metrics import compute_acc_at_k


def test_acc_at_k_follows_locagent_partial_credit_rule():
    gold = {"a.py", "b.py"}
    assert compute_acc_at_k(["a.py", "x.py", "b.py"], gold, 5) == 1.0
    assert compute_acc_at_k(["a.py", "x.py", "y.py"], gold, 5) == 0.0  # both gold files needed
    assert compute_acc_at_k(["a.py", "b.py"], gold, 1) == 1.0  # k=1 needs only min(2, 1) gold
    assert compute_acc_at_k(["x.py", "a.py"], gold, 1) == 0.0
    assert compute_acc_at_k(["a.py"], set(), 5) == 0.0
