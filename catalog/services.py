def search_products(parsed: dict) -> list:
    """Подбор товаров по разобранному запросу (category, brand, price_max, keywords). TODO."""
    raise NotImplementedError


def get_offers(product_ids: list) -> list:
    """Активные предложения в наличии для списка товаров. TODO."""
    raise NotImplementedError


def match_offer(raw) -> object:
    """Сопоставление: gtin -> match_key -> новый Product. TODO."""
    raise NotImplementedError
