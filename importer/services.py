import logging
from dataclasses import dataclass, field
from xml.etree.ElementTree import ParseError

import httpx
from django.utils import timezone

from catalog.models import Shop

from .downloader import download_feed
from .models import ImportRun
from .normalizer import InvalidOffer, normalize_offer
from .offer_writer import write_offers
from .yml_parser import iter_offers

logger = logging.getLogger(__name__)

MAX_ERROR_SAMPLES = 20


class FeedError(Exception):
    """Фид скачался, но использовать его нельзя."""


@dataclass
class _ParseCounters:
    seen: int = 0
    errors: int = 0
    samples: list = field(default_factory=list)


def _valid_offers(shop, feed, counters: _ParseCounters):
    seen_ids = set()
    for raw in iter_offers(feed):
        counters.seen += 1
        try:
            offer = normalize_offer(raw, shop.category_map)
            if offer.external_id in seen_ids:
                raise InvalidOffer("id уже был раньше в этом фиде")
        except InvalidOffer as exc:
            counters.errors += 1
            offer_id = raw.id or "без id"
            if len(counters.samples) < MAX_ERROR_SAMPLES:
                counters.samples.append(f"{offer_id}: {exc}")
            logger.warning("%s: предложение %s пропущено: %s", shop.name, offer_id, exc)
            continue
        seen_ids.add(offer.external_id)
        yield offer


def _describe(exc: Exception) -> str:
    text = str(exc).split("\n")[0]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _import_feed(shop, run: ImportRun, client: httpx.Client) -> dict:
    with download_feed(shop.feed_url, client) as feed:
        counters = _ParseCounters()
        written = write_offers(shop, _valid_offers(shop, feed, counters), seen_at=run.started_at)
    if counters.seen == 0:
        raise FeedError("в фиде нет ни одного предложения")
    return {"created": written.created, "updated": written.updated, "unchanged": written.unchanged,
            "errors": counters.errors, "error_samples": counters.samples}


def import_shop(shop: Shop, client: httpx.Client) -> ImportRun:
    run = ImportRun.objects.create(shop=shop)
    try:
        run.stats = _import_feed(shop, run, client)
    except (httpx.HTTPError, ParseError, FeedError) as exc:
        logger.warning("%s: импорт не удался: %s", shop.name, _describe(exc))
        run.status = "failed"
        run.error = _describe(exc)
    except Exception as exc:
        logger.exception("%s: импорт упал с неожиданной ошибкой", shop.name)
        run.status = "failed"
        run.error = _describe(exc)
    else:
        run.status = "success"
        shop.last_import_at = timezone.now()
        Shop.objects.filter(pk=shop.pk).update(last_import_at=shop.last_import_at)
    run.finished_at = timezone.now()
    run.save()
    return run