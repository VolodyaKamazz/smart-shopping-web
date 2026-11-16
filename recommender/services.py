"""Чистые функции без обращений к БД: данные приходят параметрами."""
from decimal import Decimal

PRIORITIES = ("balanced", "price", "speed")

WEIGHTS = {
    "balanced": {"price": 0.4, "speed": 0.3, "reliability": 0.3},
    "price": {"price": 0.7, "speed": 0.1, "reliability": 0.2},
    "speed": {"price": 0.2, "speed": 0.6, "reliability": 0.2},
}

REASONS = {
    "balanced": "лучшее сочетание цены, срока доставки и надёжности магазина",
    "price": "самая низкая итоговая стоимость с учётом доставки",
    "speed": "самая быстрая доставка среди найденных предложений",
}

SOFT_REASONS = {
    "price": "учтён приоритет цены: лучшее сочетание стоимости, срока доставки и надёжности магазина",
    "speed": "учтён приоритет скорости: лучшее сочетание срока доставки, цены и надёжности магазина",
}

BAYES_STRENGTH = 20
DEFAULT_RATING = 4.0
MAX_RATING = 5.0


def _dec(value):
    return Decimal(str(value if value is not None else 0))


def _total(offer):
    return _dec(offer["price"]) + _dec(offer.get("delivery_price"))


def _days(offer):
    low, high = offer.get("min_days"), offer.get("max_days")
    if low is None and high is None:
        return None
    if low is None:
        return float(high)
    if high is None:
        return float(low)
    return (low + high) / 2


def bayesian_rating(rating, count, prior):
    if rating is None:
        return prior
    count = count or 0
    return (count * float(rating) + BAYES_STRENGTH * prior) / (count + BAYES_STRENGTH)


def _lower_is_better(values):
    known = [v for v in values if v is not None]
    if not known:
        return [1.0] * len(values)
    low, high = min(known), max(known)
    scores = {}
    for v in known:
        scores[v] = 1.0 if high == low else (high - v) / (high - low)
    neutral = sum(scores[v] for v in known) / len(known)
    return [neutral if v is None else scores[v] for v in values]


def rank(offers: list, profile: dict) -> list:
    profile = profile or {}
    priority = profile.get("priority")
    if priority not in WEIGHTS:
        priority = "balanced"
    budget = profile.get("budget_max")
    budget = None if budget in (None, "") else _dec(budget)

    candidates = [o for o in offers if budget is None or _total(o) <= budget]
    if not candidates:
        return []

    totals = [float(_total(o)) for o in candidates]
    days = [_days(o) for o in candidates]
    rated = [float(o["rating"]) for o in candidates if o.get("rating") is not None]
    prior = sum(rated) / len(rated) if rated else DEFAULT_RATING

    price_scores = _lower_is_better(totals)
    speed_scores = _lower_is_better(days)
    reliability_scores = [
        bayesian_rating(o.get("rating"), o.get("rating_count"), prior) / MAX_RATING for o in candidates
    ]

    weights = WEIGHTS[priority]
    ranked = []
    for offer, p, s, r in zip(candidates, price_scores, speed_scores, reliability_scores):
        score = weights["price"] * p + weights["speed"] * s + weights["reliability"] * r
        ranked.append({
            **offer,
            "total_price": _total(offer),
            "score": round(score, 4),
            "priority": priority,
            "breakdown": {
                "price": round(p, 4),
                "speed": round(s, 4),
                "reliability": round(r, 4),
                "weights": dict(weights),
            },
        })
    ranked.sort(key=lambda item: (-item["score"], item["total_price"], item["id"]))
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position
        item["is_recommended"] = position == 1
    return ranked


def _money(value):
    return f"{float(value):,.0f}".replace(",", "\u00a0")


def _number(value):
    return f"{value:g}".replace(".", ",")


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _days_text(offer):
    low, high = offer.get("min_days"), offer.get("max_days")
    if low is None or high is None:
        return None
    return f"{low} дн." if low == high else f"{low}–{high} дн."


def build_explanation(best, others: list) -> tuple:
    price = _dec(best["price"])
    delivery_price = best.get("delivery_price")
    total = _dec(best["total_price"])
    days_text = _days_text(best)

    saving = Decimal(0)
    if others:
        average = sum(_dec(o["total_price"]) for o in others) / len(others)
        saving = max(average - total, Decimal(0))

    days_gain = 0.0
    best_days = _days(best)
    other_days = [d for d in (_days(o) for o in others) if d is not None]
    if best_days is not None and other_days:
        days_gain = max(sum(other_days) / len(other_days) - best_days, 0.0)

    if delivery_price is None:
        delivery_text = "стоимость доставки уточняется"
    elif _dec(delivery_price) == 0:
        delivery_text = "доставка бесплатная"
    else:
        delivery_text = f"доставка {_money(delivery_price)} ₽"

    priority = best.get("priority", "balanced")
    reason = REASONS[priority]
    if priority == "price" and any(_dec(o["total_price"]) < total for o in others):
        reason = SOFT_REASONS["price"]
    if priority == "speed" and (best_days is None or any(d < best_days for d in other_days)):
        reason = SOFT_REASONS["speed"]
    if not others:
        reason = "единственное подходящее предложение"
    parts = [
        f"{best['shop']}: {reason}.",
        f"Итого {_money(total)} ₽: товар {_money(price)} ₽, {delivery_text}.",
    ]
    if days_text:
        parts.append(f"Срок доставки: {days_text}")
    if saving > 0:
        parts.append(f"Это на {_money(saving)} ₽ дешевле, чем в среднем по остальным предложениям.")
    if days_gain > 0:
        parts.append(f"Доставка быстрее в среднем на {_number(round(days_gain, 1))} дн.")
    rating = best.get("rating")
    if rating is not None:
        count = best.get("rating_count") or 0
        stars = f"{float(rating):.1f}".replace(".", ",")
        votes = f" ({count} {_plural(count, 'оценка', 'оценки', 'оценок')})" if count else ""
        parts.append(f"Рейтинг магазина: {stars}{votes}.")

    facts = {
        "shop": best["shop"],
        "title": best.get("title", ""),
        "price": float(price),
        "delivery_price": None if delivery_price is None else float(_dec(delivery_price)),
        "total_price": float(total),
        "delivery_days": days_text,
        "saving": float(round(saving, 2)),
        "days_gain": round(days_gain, 1),
        "rating": None if rating is None else float(rating),
        "offers_compared": len(others) + 1,
        "priority": best.get("priority", "balanced"),
    }
    return " ".join(parts), facts
