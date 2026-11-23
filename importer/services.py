import logging
from dataclasses import dataclass, field
from xml.etree.ElementTree import ParseError

import httpx
from django.utils import timezone

from catalog.models import Shop

from .downloader import DownloadError, download_feed
from .lifecycle import deactivate_missing, previous_success_start, start_run
from .models import ImportRun
from .normalizer import InvalidOffer, normalize_offer
from .offer_writer import write_offers
from .yml_parser import iter_offers

logger = logging.getLogger(__name__)

MAX_ERROR_SAMPLES = 20
PARTIAL_ERROR_SHARE = 0.2


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


def _import_feed(shop, run: ImportRun, client: httpx.Client, reactivate_before=None) -> dict:
    with download_feed(shop.feed_url, client) as feed:
        counters = _ParseCounters()
        written = write_offers(shop, _valid_offers(shop, feed, counters), seen_at=run.started_at,
                               reactivate_before=reactivate_before)
    if counters.seen == 0:
        raise FeedError("в фиде нет ни одного предложения")
    stats = {"created": written.created, "updated": written.updated, "unchanged": written.unchanged,
             "errors": counters.errors, "error_samples": counters.samples}
    if written.reactivated:
        stats["reactivated"] = written.reactivated
    return stats


def _finish_successfully(shop: Shop, run: ImportRun, stats: dict, previous_start) -> None:
    total = stats["created"] + stats["updated"] + stats["unchanged"] + stats["errors"]
    run.status = "success"
    if stats["errors"] > total * PARTIAL_ERROR_SHARE:
        run.status = "partial"
        run.error = f"Пропущено {stats['errors']} из {total} записей фида: больше {PARTIAL_ERROR_SHARE:.0%}"
    elif previous_start is not None and (deactivated := deactivate_missing(shop, previous_start)):
        stats["deactivated"] = deactivated
    run.stats = stats
    shop.last_import_at = timezone.now()
    Shop.objects.filter(pk=shop.pk).update(last_import_at=shop.last_import_at)


def _fail(run: ImportRun, error: str) -> ImportRun:
    run.status = "failed"
    run.error = error
    run.finished_at = timezone.now()
    run.save()
    return run


def import_shop(shop: Shop, client: httpx.Client) -> ImportRun:
    run, started = start_run(shop)
    if not started:
        logger.warning("%s: импорт уже выполняется (запуск %s), новый не начат", shop.name, run.pk)
        return run
    previous_start = previous_success_start(shop, run)
    try:
        stats = _import_feed(shop, run, client, previous_start)
        _finish_successfully(shop, run, stats, previous_start)
    except (httpx.HTTPError, ParseError, FeedError, DownloadError) as exc:
        logger.warning("%s: импорт не удался: %s", shop.name, _describe(exc))
        return _fail(run, _describe(exc))
    except Exception as exc:
        logger.exception("%s: импорт упал с неожиданной ошибкой", shop.name)
        return _fail(run, _describe(exc))
    except (SystemExit, KeyboardInterrupt) as exc:
        logger.warning("%s: импорт прерван: %s", shop.name, str(exc) or type(exc).__name__)
        _fail(run, f"Импорт прерван: {str(exc) or type(exc).__name__}")
        raise
    run.finished_at = timezone.now()
    run.save()
    return run