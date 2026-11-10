"""Выдача каталога: подбор товаров и их предложений."""
from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Q

from .models import Category, Offer, Product
from .normalize import normalize_brand, normalize_text

MAX_PRODUCTS = 50

AVAILABLE_OFFER = {"is_active": True, "in_stock": True, "shop__is_active": True}


def _price(parsed: dict, key: str):
    value = parsed.get(key)
    return None if value in (None, "") else Decimal(str(value))


def _category_ids(slug: str) -> list:
    """id категории и всех вложенных в неё: запрос «электроника» включает смартфоны и ноутбуки."""
    ids = list(Category.objects.filter(slug=slug).values_list("pk", flat=True))
    level = ids
    while level:
        level = [pk for pk in Category.objects.filter(parent_id__in=level).values_list("pk", flat=True)
                 if pk not in ids]
        ids += level
    return ids


def _query_words(keywords: list) -> list:
    return list(dict.fromkeys(normalize_text(" ".join(keywords)).split()))


def _words_found_in_catalog(words: list) -> list:
    if not words:
        return []
    counts = Product.objects.aggregate(
        **{f"w{i}": Count("pk", filter=Q(search_text__contains=f" {word} ")) for i, word in enumerate(words)})
    return [word for i, word in enumerate(words) if counts[f"w{i}"]]


def search_products(parsed: dict) -> list:
    price_min, price_max = _price(parsed, "price_min"), _price(parsed, "price_max")
    conditions = dict(AVAILABLE_OFFER)
    if price_min is not None:
        conditions["price__gte"] = price_min
    if price_max is not None:
        conditions["price__lte"] = price_max

    words = _query_words(parsed.get("keywords") or [])
    known_words = _words_found_in_catalog(words)
    has_filters = bool(parsed.get("category") or parsed.get("brand")) or price_min is not None or price_max is not None
    if words and not known_words and not has_filters:
        return []

    products = Product.objects.filter(Exists(Offer.objects.filter(product=OuterRef("pk"), **conditions)))
    if parsed.get("category"):
        products = products.filter(category_id__in=_category_ids(parsed["category"]))
    if parsed.get("brand"):
        products = products.filter(brand__normalized_name=normalize_brand(parsed["brand"]))
    for word in known_words:
        products = products.filter(search_text__contains=f" {word} ")

    offer_count = Count("offers", filter=Q(**{f"offers__{lookup}": value for lookup, value in conditions.items()}))
    return list(products.annotate(offer_count=offer_count).order_by("-offer_count", "pk")[:MAX_PRODUCTS])


def get_offers(product_ids: list) -> list:
    offers = Offer.objects.filter(product_id__in=product_ids, **AVAILABLE_OFFER)
    return list(offers.select_related("shop", "product").order_by("price", "pk"))