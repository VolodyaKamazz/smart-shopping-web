import logging

from django.db import transaction
from django.db.models import Avg

from catalog.models import Shop
from delivery.services import calc_deliveries, unknown_delivery
from recommender.services import DEFAULT_PRIORITY, Candidate, rank

from .models import SearchResult

logger = logging.getLogger(__name__)

MAX_RESULTS = 50


def build_profile(search):
    user = search.user
    prior = Shop.objects.filter(is_active=True, rating__isnull=False).aggregate(value=Avg("rating"))["value"]
    return {
        "priority": user.delivery_priority if user else DEFAULT_PRIORITY,
        "budget_max": user.budget_max if user else None,
        "prior_rating": prior,
    }


def build_candidate(offer, delivery, preference=0.0):
    terms = offer.terms
    return Candidate(
        offer_id=offer.pk, shop_id=offer.shop_id, price=offer.price,
        delivery_price=delivery.price, delivery_days=delivery.max_days,
        in_stock=offer.in_stock, is_active=offer.is_active and offer.shop.is_active,
        rating=terms.rating, rating_count=terms.rating_count,
        warranty_months=terms.warranty_months, return_days=terms.return_days, preference=preference)


def calc_deliveries_safely(search, offers, priority):
    try:
        return calc_deliveries(offers, search.city, priority)
    except Exception:
        logger.exception("Ошибка расчёта доставки для запроса %s", search.pk)
        search.degraded = True
        search.save(update_fields=["degraded"])
        return {offer.pk: unknown_delivery() for offer in offers}


def rank_offers(search, offers):
    profile = build_profile(search)
    deliveries = calc_deliveries_safely(search, offers, profile["priority"])
    candidates = {offer.pk: build_candidate(offer, deliveries[offer.pk]) for offer in offers}
    return rank(list(candidates.values()), profile)[:MAX_RESULTS], candidates, deliveries


def build_result(search, offer, item, candidate, delivery):
    return SearchResult(
        search=search, offer=offer, rank=item.rank, score=item.score, breakdown=item.breakdown,
        item_price=candidate.price, total_price=candidate.total_price, is_recommended=item.is_recommended,
        delivery_price=delivery.price, delivery_min_days=delivery.min_days, delivery_max_days=delivery.max_days,
        delivery_source=delivery.source, delivery_method=delivery.method)


def rank_and_save(search, offers):
    ranked, candidates, deliveries = rank_offers(search, offers) if offers else ([], {}, {})
    offers_by_id = {offer.pk: offer for offer in offers}
    results = [build_result(search, offers_by_id[item.offer_id], item, candidates[item.offer_id],
                            deliveries[item.offer_id]) for item in ranked]
    with transaction.atomic():
        search.results.all().delete()
        SearchResult.objects.bulk_create(results)
        search.recommended_offer = results[0].offer if results else None
        search.save(update_fields=["recommended_offer"])
    return len(results)
