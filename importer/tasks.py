def import_feeds(shop_id=None):
    """Скачивание и разбор YML-фидов (iterparse), нормализация, upsert по content_hash,
    история цен, деактивация пропавших, затем favorites.services.check_price_changes. TODO."""
    raise NotImplementedError
