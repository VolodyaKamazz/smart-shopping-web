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


def current_sort(params):
    return params.get("sort") if params.get("sort") in SORTS else ""


def select_results(search, params):
    results = list(search.results.select_related("offer__shop"))
    price_max = _non_negative_int(params.get("price_max"))
    max_days = _non_negative_int(params.get("delivery_max_days"))
    if price_max is not None:
        results = [r for r in results if r.item_price <= price_max]
    if max_days is not None:
        results = [r for r in results if r.delivery_max_days is not None and r.delivery_max_days <= max_days]
    sort = current_sort(params)
    if sort:
        results.sort(key=SORTS[sort])
    return results
