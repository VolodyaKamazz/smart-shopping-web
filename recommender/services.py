"""Чистые функции без обращений к БД: данные приходят параметрами."""
from dataclasses import dataclass
from decimal import Decimal

WEIGHTS = {
    "balanced": {"price": 0.40, "delivery": 0.20, "reliability": 0.20, "terms": 0.10, "preference": 0.10},
    "price": {"price": 0.60, "delivery": 0.10, "reliability": 0.15, "terms": 0.10, "preference": 0.05},
    "speed": {"price": 0.25, "delivery": 0.45, "reliability": 0.15, "terms": 0.10, "preference": 0.05},
}
DEFAULT_PRIORITY = "balanced"
PRIOR_WEIGHT = 50
MAX_RATING = 5.0
SCORE_PRECISION = 9


@dataclass(frozen=True)
class Candidate:
    offer_id: int
    shop_id: int
    price: Decimal
    delivery_price: Decimal | None
    delivery_days: int | None
    in_stock: bool
    is_active: bool
    rating: Decimal | None
    rating_count: int
    warranty_months: int | None
    return_days: int | None
    preference: float = 0.0

    @property
    def total_price(self):
        return self.price + (self.delivery_price or 0)


@dataclass(frozen=True)
class Ranked:
    offer_id: int
    rank: int
    score: float
    breakdown: dict
    is_recommended: bool


def bayesian_rating(rating, count, prior, prior_weight=PRIOR_WEIGHT):
    if rating is None or count <= 0:
        return prior
    rating = min(max(float(rating), 0.0), MAX_RATING)
    return (count * rating + prior_weight * prior) / (count + prior_weight)


def normalize(values, higher_is_better):
    low, high = min(values), max(values)
    if high == low:
        return [1.0] * len(values)
    span = high - low
    return [(value - low) / span if higher_is_better else (high - value) / span for value in values]


def fill_unknown(values):
    known = [value for value in values if value is not None]
    worst = max(known) if known else 0
    return [worst if value is None else value for value in values]


def prior_rating(candidates, profile):
    if profile.get("prior_rating") is not None:
        return float(profile["prior_rating"])
    ratings = {c.shop_id: float(c.rating) for c in candidates if c.rating is not None}
    return sum(ratings.values()) / len(ratings) if ratings else 0.0


def passes_hard_conditions(candidate, budget_max):
    if not (candidate.is_active and candidate.in_stock):
        return False
    return budget_max is None or candidate.total_price <= budget_max


def effective_totals(candidates):
    delivery_prices = fill_unknown([c.delivery_price for c in candidates])
    return [float(c.price) + float(extra) for c, extra in zip(candidates, delivery_prices)]


def criteria_values(candidates, totals, days, prior):
    warranty = normalize([c.warranty_months or 0 for c in candidates], higher_is_better=True)
    returns = normalize([c.return_days or 0 for c in candidates], higher_is_better=True)
    return {
        "price": normalize(totals, higher_is_better=False),
        "delivery": normalize(days, higher_is_better=False),
        "reliability": [bayesian_rating(c.rating, c.rating_count, prior) / MAX_RATING for c in candidates],
        "terms": [(w + r) / 2 for w, r in zip(warranty, returns)],
        "preference": [min(max(c.preference, 0.0), 1.0) for c in candidates],
    }


def rank(offers: list, profile: dict) -> list:
    weights = WEIGHTS.get(profile.get("priority"), WEIGHTS[DEFAULT_PRIORITY])
    candidates = [c for c in offers if passes_hard_conditions(c, profile.get("budget_max"))]
    if not candidates:
        return []
    totals = effective_totals(candidates)
    days = fill_unknown([c.delivery_days for c in candidates])
    values = criteria_values(candidates, totals, days, prior_rating(candidates, profile))
    scored = []
    for index, candidate in enumerate(candidates):
        parts = {name: weights[name] * values[name][index] for name in weights}
        tie_break = (totals[index], days[index], candidate.delivery_price is None, candidate.offer_id)
        scored.append((sum(parts.values()), tie_break, parts, candidate.offer_id))
    scored.sort(key=lambda item: (-round(item[0], SCORE_PRECISION), item[1]))
    return [Ranked(offer_id, position, round(score, 4), {name: round(part, 4) for name, part in parts.items()},
                   position == 1)
            for position, (score, _, parts, offer_id) in enumerate(scored, start=1)]


def build_explanation(best, others: list) -> tuple:
    """Факты (цена, доставка, срок, экономия) -> текст по шаблону. Возвращает (text, facts). TODO."""
    raise NotImplementedError
