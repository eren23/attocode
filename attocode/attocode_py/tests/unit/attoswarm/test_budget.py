from attoswarm.coordinator.budget import BudgetCounter


def test_budget_uses_fallback_chars_to_tokens() -> None:
    b = BudgetCounter(max_tokens=100, max_cost_usd=10.0, chars_per_token=4.0)
    b.add_usage(token_usage=None, cost_usd=None, text="x" * 40)
    assert b.used_tokens == 10


def test_budget_hard_exceeded_on_cost() -> None:
    b = BudgetCounter(max_tokens=1000, max_cost_usd=1.0)
    b.add_usage(token_usage={"total": 1}, cost_usd=1.2)
    assert b.hard_exceeded() is True
