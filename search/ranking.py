import logging

from django.db import transaction
from django.utils import timezone

from delivery import services as delivery_services
from recommender import services as recommender

from .deadline import DELIVERY_BUDGET, Deadline
from .degraded import DEADLINE_HIT, DELIVERY_FAILED, EXPLANATION_FAILED
from .models import SearchResult

logger = logging.getLogger(__name__)

PRIORITIES = recommender.PRIORITIES
CRITERIA = [("balanced", "Баланс"), ("price", "Цена"), ("speed", "Скорость")]
MAX_RESULTS = 50
DELIVERY_FIELDS = ("delivery_price", "delivery_min_days", "delivery_max_days", "delivery_source", "delivery_method")


def delivery_map(offers, city, priority="balanced", deadline=None, degraded=None):
    degraded = set() if degraded is None else degraded
    if city is None:
        return {offer.id: None for offer in offers}
    stage = Deadline(DELIVERY_BUDGET) if deadline is None else deadline.share(DELIVERY_BUDGET)
    try:
        context = delivery_services.DeliveryContext(offers, city)
    except Exception:
        logger.exception("Не удалось загрузить правила доставки")
        degraded.add(DELIVERY_FAILED)
        return {offer.id: None for offer in offers}
    infos = {}
    for offer in offers:
        if stage.expired:
            degraded.add(DEADLINE_HIT)
            infos[offer.id] = None
            continue
        try:
            infos[offer.id] = delivery_services.calc_delivery(offer, city, priority, context)
        except Exception:
            logger.exception("Не удалось рассчитать доставку для предложения %s", offer.id)
            degraded.add(DELIVERY_FAILED)
            infos[offer.id] = None
    return infos


def delivery_fields(info):
    if info is None:
        return dict(zip(DELIVERY_FIELDS, (None, None, None, "", "")))
    return dict(zip(DELIVERY_FIELDS, (info.price, info.min_days, info.max_days, info.source, info.method)))


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


def stale_shop_names(offers):
    now = timezone.now()
    shops = {offer.shop_id: offer.shop for offer in offers}
    return sorted(shop.name for shop in shops.values() if shop.has_stale_data(now))


def apply_recommendation(search, ranked, offers_by_id, priority, base_facts=None, degraded=None):
    degraded = set() if degraded is None else degraded
    facts = dict(base_facts or {})
    facts["criterion"] = priority
    search.recommended_offer = None
    search.explanation = ""
    if ranked:
        search.recommended_offer = offers_by_id[ranked[0]["id"]]
        try:
            search.explanation, explained = recommender.build_explanation(ranked[0], ranked[1:])
            facts.update(explained)
        except Exception:
            logger.exception("Не удалось построить объяснение для запроса %s", search.pk)
            degraded.add(EXPLANATION_FAILED)
    facts["degraded_reasons"] = sorted(degraded)
    search.facts = facts
    search.degraded = bool(degraded)
    search.save(update_fields=["recommended_offer", "explanation", "facts", "degraded"])


def rank_and_save(search, offers, deadline=None):
    degraded = set()
    profile = profile_for(search)
    infos = delivery_map(offers, search.city, profile["priority"], deadline, degraded)
    offers_by_id = {offer.id: offer for offer in offers}
    ranked = recommender.rank([offer_input(o, infos[o.id]) for o in offers], profile)[:MAX_RESULTS]

    rows = [
        SearchResult(
            search=search, offer=offers_by_id[item["id"]], rank=item["rank"], score=item["score"],
            breakdown=item["breakdown"], item_price=item["price"], total_price=item["total_price"],
            is_recommended=item["is_recommended"], **delivery_fields(infos[item["id"]]))
        for item in ranked
    ]
    with transaction.atomic():
        search.results.all().delete()
        SearchResult.objects.bulk_create(rows)

    budget = profile["budget_max"]
    base_facts = {
        "budget_max": None if budget is None else float(budget),
        "excluded_over_budget": len(offers) - len(ranked) if budget is not None else 0,
        "stale_shops": stale_shop_names([offers_by_id[item["id"]] for item in ranked]),
    }
    apply_recommendation(search, ranked, offers_by_id, profile["priority"], base_facts, degraded)
    return len(ranked)


def recalculate(search, priority):
    results = list(search.results.select_related("offer__shop"))
    degraded = set()
    infos = delivery_map([r.offer for r in results], search.city, priority, degraded=degraded)
    inputs = [offer_input(r.offer, infos[r.offer_id]) | {"price": r.item_price} for r in results]
    ranked = recommender.rank(inputs, {"priority": priority})
    by_result = {r.offer_id: r for r in results}
    for item in ranked:
        result = by_result[item["id"]]
        result.rank, result.score = item["rank"], item["score"]
        result.breakdown, result.is_recommended = item["breakdown"], item["is_recommended"]
        result.total_price = item["total_price"]
        for name, value in delivery_fields(infos[item["id"]]).items():
            setattr(result, name, value)
    SearchResult.objects.bulk_update(
        results, ["rank", "score", "breakdown", "is_recommended", "total_price", *DELIVERY_FIELDS])
    kept = ("budget_max", "excluded_over_budget", "stale_shops")
    base_facts = {key: search.facts[key] for key in kept if key in search.facts}
    apply_recommendation(search, ranked, {r.offer_id: r.offer for r in results}, priority, base_facts, degraded)
