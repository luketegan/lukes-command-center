from dataclasses import dataclass, field

from .errors import BudgetExhausted

LIMIT_NAMES = {
    "steps": "max_steps", "searches": "max_searches",
    "fetches": "max_fetches", "model_calls": "max_model_calls",
    "total_tokens": "max_total_tokens",
}


@dataclass
class Budgets:
    limits: dict
    usage: dict = field(default_factory=lambda: {
        "steps": 0, "searches": 0, "fetches": 0,
        "model_calls": 0, "total_tokens": 0,
    })

    def spend(self, name: str, amount: int = 1) -> None:
        limit_name = LIMIT_NAMES[name]
        if self.usage[name] + amount > int(self.limits[limit_name]):
            raise BudgetExhausted(f"{limit_name} exhausted")
        self.usage[name] += amount

    def record_tokens(self, amount: int) -> None:
        """Tokens are already spent when the model replies, so always count them."""
        self.usage["total_tokens"] += amount

    def check_tokens(self) -> None:
        if self.usage["total_tokens"] >= int(self.limits["max_total_tokens"]):
            raise BudgetExhausted("max_total_tokens exhausted")

    def remaining(self) -> dict:
        return {
            key: int(self.limits[limit_name]) - self.usage[key]
            for key, limit_name in LIMIT_NAMES.items()
        }
