import logging
import time

from django.utils import timezone

from catalog import services as catalog_services
from catalog.models import Brand, Category

from .models import SearchRequest, SearchResult
from .parser import parse_query

logger = logging.getLogger(__name__)

MAX_RESULTS = 50


def load_dictionaries():
    categories = list(Category.objects.values("slug", "name", "keywords"))
    brands = list(Brand.objects.values("name", "normalized_name"))
    return categories, brands


def _call(function, *args):
    try:
        return function(*args)
    except NotImplementedError:
        return []


def _set_step(search, step):
    search.step = step
    search.save(update_fields=["step"])


def save_results(search, offers):
    search.results.all().delete()
    ordered = sorted(offers, key=lambda offer: offer.price)[:MAX_RESULTS]
    SearchResult.objects.bulk_create([
        SearchResult(search=search, offer=offer, rank=position, score=0.0, breakdown={},
                     item_price=offer.price, total_price=offer.price)
        for position, offer in enumerate(ordered, start=1)
    ])
    return len(ordered)


def run_search(search_id):
    started = time.monotonic()
    search = SearchRequest.objects.get(pk=search_id)
    search.status = "running"
    search.step = "Разбор запроса"
    search.save(update_fields=["status", "step"])
    try:
        categories, brands = load_dictionaries()
        search.parsed = parse_query(search.raw_query, categories, brands)
        search.save(update_fields=["parsed"])

        _set_step(search, "Подбор товаров")
        products = _call(catalog_services.search_products, search.parsed)
        product_ids = [getattr(product, "pk", product) for product in products]

        _set_step(search, "Поиск предложений")
        offers = _call(catalog_services.get_offers, product_ids) if product_ids else []
        save_results(search, offers)

        search.status = "done"
    except Exception:
        logger.exception("Ошибка в run_search для запроса %s", search_id)
        search.status = "failed"
    search.step = ""
    search.finished_at = timezone.now()
    search.duration_ms = int((time.monotonic() - started) * 1000)
    search.save(update_fields=["status", "step", "finished_at", "duration_ms"])
