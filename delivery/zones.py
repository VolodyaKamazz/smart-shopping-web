from .info import SOURCE_ZONE, DeliveryInfo
from .models import DeliveryMethod, ZoneRate
from .tariff_cache import get_tariff, put_tariff
from .weights import offer_weight_class


def _load_tariff(zone_from, zone_to, weight_class):
    rate = (ZoneRate.objects
            .filter(zone_from=zone_from, zone_to=zone_to, max_weight_kg__gte=weight_class)
            .order_by("max_weight_kg").first())
    if rate is None:
        return None
    return DeliveryInfo(rate.price, rate.min_days, rate.max_days, SOURCE_ZONE, DeliveryMethod.PICKUP.value)


def zone_delivery(offer, city, memo=None):
    origin_city = offer.shop.origin_city
    if origin_city is None or city is None:
        return None
    weight_class = offer_weight_class(offer)
    if weight_class is None:
        return None
    memo_key = (origin_city.zone, weight_class)
    if memo is not None and memo_key in memo:
        return memo[memo_key]
    info = get_tariff(origin_city.zone, city.zone, weight_class)
    if info is None:
        info = _load_tariff(origin_city.zone, city.zone, weight_class)
        if info is not None:
            put_tariff(origin_city.zone, city.zone, weight_class, info)
    if memo is not None:
        memo[memo_key] = info
    return info
