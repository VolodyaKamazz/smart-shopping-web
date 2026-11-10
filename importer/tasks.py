"""Задачи импорта: их запускает расписание Django-Q2 (importer/schedule.py) и команда import_feeds."""
from catalog.models import Shop

from .downloader import make_client
from .services import import_shop


def import_feeds(shop_id: int | None = None) -> list:
    shops = Shop.objects.filter(is_active=True).exclude(feed_url="")
    if shop_id is not None:
        shops = shops.filter(pk=shop_id)
    shops = list(shops.order_by("pk"))
    if not shops:
        return []
    with make_client() as client:
        return [import_shop(shop, client).pk for shop in shops]
