import logging
from decimal import Decimal

from delivery import services as delivery_services
from delivery.models import ShopDeliveryRule
from delivery.services import DeliveryInfo
from recommender import services as recommender

from .models import SearchResult

logger = logging.getLogger(__name__)

PRIORITIES = recommender.PRIORITIES
CRITERIA = [("balanced", "Баланс"), ("price", "Цена"), ("speed", "Скорость")]
MAX_RESULTS = 50


class RuleLookup:
    def __init__(self, offers, city):
        self.city = city
        self.rules = {}
        rules = ShopDeliveryRule.objects.filter(shop_id__in={offer.shop_id for offer in offers})
        for rule in rules:
            self.rules.setdefault(rule.shop_id, []).append(rule)

    def get(self, offer):
        shop_rules = self.rules.get(offer.shop_id, [])
        rule = next((r for r in shop_rules if r.city_id == self.city.pk), None)
        rule = rule or next((r for r in shop_rules if r.city_id is None), None)
        if rule is None:
            return None
        free = rule.free_from is not None and offer.price >= rule.free_from
        return DeliveryInfo(price=Decimal(0) if free else rule.cost, min_days=rule.min_days,
                            max_days=rule.max_days, source="shop")


def delivery_map(offers, city):
    if city is None:
        return {offer.id: None for offer in offers}
    lookup = None
    infos = {}
    for offer in offers:
        try:
            infos[offer.id] = delivery_services.calc_delivery(offer, city)
        except NotImplementedError:
            lookup = lookup or RuleLookup(offers, city)
            infos[offer.id] = lookup.get(offer)
        except Exception:
            logger.exception("Не удалось рассчитать доставку для предложения %s", offer.id)
            infos[offer.id] = None
    return infos


def offer_input(offer, info):
    return {
        "id": offer.id,
        "shop": offer.shop.name,
        "title": offer.title_raw,
        "price": offer.price,
        "delivery_price": info.price if info else None,
        "min_days": info.min_days if info else None,
        "max_days": info.max_days if info else None,
        "rating": offer.shop.rating,
        "rating_count": offer.shop.rating_count,
    }


def profile_for(search):
    user = search.user
    priority = user.delivery_priority if user else "balanced"
    return {"priority": priority if priority in PRIORITIES else "balanced",
            "budget_max": user.budget_max if user else None}


def apply_recommendation(search, ranked, offers_by_id, priority, base_facts=None):
    facts = dict(base_facts or {})
    facts["criterion"] = priority
    if ranked:
        text, explained = recommender.build_explanation(ranked[0], ranked[1:])
        facts.update(explained)
        search.recommended_offer = offers_by_id[ranked[0]["id"]]
        search.explanation = text
    else:
        search.recommended_offer = None
        search.explanation = ""
    search.facts = facts
    search.save(update_fields=["recommended_offer", "explanation", "facts"])


def rank_and_save(search, offers):
    profile = profile_for(search)
    infos = delivery_map(offers, search.city)
    offers_by_id = {offer.id: offer for offer in offers}
    ranked = recommender.rank([offer_input(o, infos[o.id]) for o in offers], profile)[:MAX_RESULTS]

    search.results.all().delete()
    rows = []
    for item in ranked:
        info = infos[item["id"]]
        rows.append(SearchResult(
            search=search, offer=offers_by_id[item["id"]], rank=item["rank"], score=item["score"],
            breakdown=item["breakdown"], item_price=item["price"],
            delivery_price=info.price if info else None,
            delivery_min_days=info.min_days if info else None,
            delivery_max_days=info.max_days if info else None,
            delivery_source=info.source if info else "",
            total_price=item["total_price"], is_recommended=item["is_recommended"]))
    SearchResult.objects.bulk_create(rows)

    budget = profile["budget_max"]
    base_facts = {
        "budget_max": None if budget is None else float(budget),
        "excluded_over_budget": len(offers) - len(ranked) if budget is not None else 0,
    }
    apply_recommendation(search, ranked, offers_by_id, profile["priority"], base_facts)
    return len(ranked)


def recalculate(search, priority):
    results = list(search.results.select_related("offer__shop"))
    inputs = [offer_input(r.offer, _stored_info(r)) | {"price": r.item_price} for r in results]
    ranked = recommender.rank(inputs, {"priority": priority})
    by_result = {r.offer_id: r for r in results}
    for item in ranked:
        result = by_result[item["id"]]
        result.rank, result.score = item["rank"], item["score"]
        result.breakdown, result.is_recommended = item["breakdown"], item["is_recommended"]
    SearchResult.objects.bulk_update(results, ["rank", "score", "breakdown", "is_recommended"])
    base_facts = {key: search.facts.get(key) for key in ("budget_max", "excluded_over_budget") if key in search.facts}
    apply_recommendation(search, ranked, {r.offer_id: r.offer for r in results}, priority, base_facts)


def _stored_info(result):
    if result.delivery_price is None:
        return None
    return DeliveryInfo(price=result.delivery_price, min_days=result.delivery_min_days,
                        max_days=result.delivery_max_days, source=result.delivery_source)
