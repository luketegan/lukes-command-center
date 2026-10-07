from dataclasses import dataclass, field

from .errors import BudgetExhausted


@dataclass
class Budgets:
    limits: dict
    usage: dict = field(default_factory=lambda: {
        "steps": 0, "searches": 0, "fetches": 0,
        "model_calls": 0, "total_tokens": 0,
    })

    def spend(self, name: str, amount: int = 1) -> None:
        limit_name = {
            "steps": "max_steps", "searches": "max_searches",
            "fetches": "max_fetches", "model_calls": "max_model_calls",
            "total_tokens": "max_total_tokens",
        }[name]
        if self.usage[name] + amount > int(self.limits[limit_name]):
            raise BudgetExhausted(f"{limit_name} exhausted")
        self.usage[name] += amount

    def remaining(self) -> dict:
        return {
            key: int(self.limits[limit_name]) - self.usage[key]
            for key, limit_name in {
                "steps": "max_steps", "searches": "max_searches",
                "fetches": "max_fetches", "model_calls": "max_model_calls",
                "total_tokens": "max_total_tokens",
            }.items()
        }

