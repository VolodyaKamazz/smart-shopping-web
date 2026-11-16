from collections import defaultdict
from decimal import Decimal

from django.db.models import F, Q

from .info import SOURCE_SHOP, DeliveryInfo
from .models import DeliveryMethod, ShopDeliveryRule

FREE = Decimal("0.00")
METHOD_ORDER = (DeliveryMethod.COURIER.value, DeliveryMethod.PICKUP.value)


def load_rules(shop_ids, city):
    rules = ShopDeliveryRule.objects.filter(shop_id__in=shop_ids, is_active=True)
    if city is None:
        rules = rules.filter(city__isnull=True)
    else:
        rules = rules.filter(Q(city_id=city.pk) | Q(city__isnull=True))
    chosen = defaultdict(dict)
    for rule in rules.order_by(F("city_id").desc(nulls_last=True), "pk"):
        chosen[rule.shop_id].setdefault(rule.method, rule)
    return chosen


def shop_delivery_options(offer, shop_rules):
    options = []
    for method in METHOD_ORDER:
        rule = shop_rules.get(method)
        if rule is None:
            continue
        is_free = rule.free_from is not None and offer.price >= rule.free_from
        options.append(DeliveryInfo(FREE if is_free else rule.cost, rule.min_days, rule.max_days, SOURCE_SHOP, method))
    return options
