from decimal import Decimal
from itertools import count

from catalog.models import Category, Offer, Product, Shop
from delivery.models import City, ShopDeliveryRule, ZoneRate

_external_ids = count(1)


def make_city(name, zone):
    return City.objects.create(name=name, region=name, zone=zone)


def make_shop(name="Магазин", origin_city=None):
    return Shop.objects.create(name=name, origin_city=origin_city)


def make_offer(shop, price="10000", category=None, **fields):
    product = None
    if category is not None:
        product = Product.objects.create(category=category, name="Товар", search_text=" товар ")
    return Offer.objects.create(shop=shop, product=product, external_id=str(next(_external_ids)),
                                url="https://shop.example/p", title_raw="Товар", price=Decimal(price), **fields)


def make_rule(shop, cost, min_days=1, max_days=3, city=None, free_from=None, method="courier", is_active=True):
    return ShopDeliveryRule.objects.create(
        shop=shop, city=city, method=method, cost=Decimal(cost),
        free_from=None if free_from is None else Decimal(free_from),
        min_days=min_days, max_days=max_days, is_active=is_active)


def make_rate(zone_from, zone_to, max_weight_kg, price, min_days=2, max_days=5):
    return ZoneRate.objects.create(zone_from=zone_from, zone_to=zone_to, max_weight_kg=Decimal(max_weight_kg),
                                   price=Decimal(price), min_days=min_days, max_days=max_days)


def make_category(slug, parent=None):
    return Category.objects.create(name=slug, slug=slug, parent=parent)
