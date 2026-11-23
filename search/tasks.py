import logging
import time

from django.utils import timezone

from catalog import services as catalog_services
from catalog.models import Brand, Category

from . import ranking
from .deadline import SEARCH_DEADLINE, Deadline
from .models import SearchRequest
from .parser import parse_query

logger = logging.getLogger(__name__)


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


def within_budget(offers, parsed):
    low, high = parsed.get("price_min"), parsed.get("price_max")
    return [offer for offer in offers
            if (low is None or offer.price >= low) and (high is None or offer.price <= high)]


def run_search(search_id):
    started = time.monotonic()
    search = SearchRequest.objects.get(pk=search_id)
    waited = max(0.0, (timezone.now() - search.created_at).total_seconds())
    deadline = Deadline(SEARCH_DEADLINE - waited, started)
    search.status = "running"
    search.step = "Разбор запроса"
    search.save(update_fields=["status", "step"])
    interrupted = None
    try:
        categories, brands = load_dictionaries()
        search.parsed = parse_query(search.raw_query, categories, brands)
        search.save(update_fields=["parsed"])

        _set_step(search, "Подбор товаров")
        products = catalog_services.search_products(search.parsed)
        product_ids = [getattr(product, "pk", product) for product in products]

        _set_step(search, "Поиск предложений")
        offers = catalog_services.get_offers(product_ids) if product_ids else []

        _set_step(search, "Расчёт доставки и оценка")
        ranking.rank_and_save(search, within_budget(offers, search.parsed), deadline)

        search.status = "done"
    except Exception:
        logger.exception("Ошибка в run_search для запроса %s", search_id)
        search.status = "failed"
    except (SystemExit, KeyboardInterrupt) as exc:
        logger.warning("Запрос %s прерван: %s", search_id, str(exc) or type(exc).__name__)
        search.status = "failed"
        interrupted = exc
    search.step = ""
    search.finished_at = timezone.now()
    search.duration_ms = int((time.monotonic() - started) * 1000)
    if search.duration_ms > SEARCH_DEADLINE * 1000:
        logger.warning("Запрос %s выполнялся %d мс, больше дедлайна", search_id, search.duration_ms)
    search.save(update_fields=["status", "step", "finished_at", "duration_ms"])
    if interrupted is not None:
        raise interrupted
