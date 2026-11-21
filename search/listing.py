from decimal import Decimal, InvalidOperation

from django.db.models import Count

SORTS = {
    "price": lambda r: (r.item_price, r.rank),
    "total": lambda r: (r.total_price, r.rank),
    "delivery": lambda r: (r.delivery_max_days is None, r.delivery_max_days or 0, r.delivery_min_days or 0, r.total_price),
    "rating": lambda r: (r.offer.shop.rating is None, -(r.offer.shop.rating or 0), r.total_price),
}


def _non_negative_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _non_negative_price(value):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def _shop_filter(params):
    values = params.getlist("shop") if hasattr(params, "getlist") else [params.get("shop")]
    ids, names = set(), set()
    for value in values:
        for part in str(value or "").split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
            elif part:
                names.add(part.lower())
    return ids, names


def shops_of(search):
    rows = (search.results.values("offer__shop_id", "offer__shop__name")
            .annotate(count=Count("id")).order_by("offer__shop__name"))
    return [{"id": r["offer__shop_id"], "name": r["offer__shop__name"], "count": r["count"]} for r in rows]


def current_sort(params):
    return params.get("sort") if params.get("sort") in SORTS else ""


def select_results(search, params):
    results = list(search.results.select_related("offer__shop"))
    price_min = _non_negative_price(params.get("price_min"))
    price_max = _non_negative_price(params.get("price_max"))
    max_days = _non_negative_int(params.get("delivery_max_days"))
    shop_ids, shop_names = _shop_filter(params)
    if price_min is not None:
        results = [r for r in results if r.item_price >= price_min]
    if price_max is not None:
        results = [r for r in results if r.item_price <= price_max]
    if shop_ids or shop_names:
        results = [r for r in results
                   if r.offer.shop_id in shop_ids or r.offer.shop.name.lower() in shop_names]
    if max_days is not None:
        results = [r for r in results if r.delivery_max_days is not None and r.delivery_max_days <= max_days]
    sort = current_sort(params)
    if sort:
        results.sort(key=SORTS[sort])
    return results
