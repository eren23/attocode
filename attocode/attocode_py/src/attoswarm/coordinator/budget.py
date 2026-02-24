"""Budget accounting with native + fallback token estimation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BudgetCounter:
    max_tokens: int
    max_cost_usd: float
    chars_per_token: float = 4.0
    used_tokens: int = 0
    used_cost_usd: float = 0.0

    def add_usage(self, token_usage: dict[str, int] | None, cost_usd: float | None, text: str = "") -> None:
        if token_usage and "total" in token_usage:
            self.used_tokens += max(int(token_usage["total"]), 0)
        elif text:
            self.used_tokens += max(int(len(text) / max(self.chars_per_token, 1.0)), 1)
        if cost_usd is not None:
            self.used_cost_usd += max(cost_usd, 0.0)

    def hard_exceeded(self) -> bool:
        return self.used_tokens >= self.max_tokens or self.used_cost_usd >= self.max_cost_usd

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tokens_used": self.used_tokens,
            "tokens_max": self.max_tokens,
            "cost_used_usd": round(self.used_cost_usd, 6),
            "cost_max_usd": self.max_cost_usd,
        }
