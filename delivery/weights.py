from decimal import Decimal

WEIGHT_CLASSES_KG = tuple(Decimal(value) for value in ("0.5", "1", "2", "3", "5"))
DEFAULT_CATEGORY_WEIGHT_KG = Decimal("2")
CATEGORY_WEIGHT_KG = {
    "headphones": Decimal("0.5"),
    "smartphones": Decimal("0.5"),
    "tablets": Decimal("1"),
    "laptops": Decimal("3"),
}


def weight_class(weight_kg):
    return next((limit for limit in WEIGHT_CLASSES_KG if weight_kg <= limit), None)


def category_weight_kg(category):
    visited = set()
    while category is not None and category.pk not in visited:
        if category.slug in CATEGORY_WEIGHT_KG:
            return CATEGORY_WEIGHT_KG[category.slug]
        visited.add(category.pk)
        category = category.parent
    return DEFAULT_CATEGORY_WEIGHT_KG


def offer_weight_kg(offer):
    if offer.weight_g:
        return Decimal(offer.weight_g) / 1000
    return category_weight_kg(offer.product.category if offer.product_id else None)


def offer_weight_class(offer):
    return weight_class(offer_weight_kg(offer))
