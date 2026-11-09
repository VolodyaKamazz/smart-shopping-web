from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from itertools import islice
from typing import NamedTuple

from django.db import transaction

from catalog.matching import match_offers
from catalog.models import Offer, PriceHistory

from .normalizer import NormalizedOffer

CHUNK_SIZE = 500

UPDATE_FIELDS = ["url", "title_raw", "price", "old_price", "in_stock", "warranty_months", "weight_g",
                 "params", "content_hash", "last_seen_at", "updated_at"]


class KnownOffer(NamedTuple):
    pk: int
    content_hash: str
    price: Decimal
    in_stock: bool
    product_id: int | None


@dataclass
class WriteStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


def _chunks(items: Iterable, size: int) -> Iterator[list]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _new_offer(shop, item: NormalizedOffer, content_hash: str, seen_at, product_id=None) -> Offer:
    return Offer(
        shop=shop, product_id=product_id, external_id=item.external_id, url=item.url, title_raw=item.title,
        price=item.price, old_price=item.old_price, in_stock=item.in_stock, warranty_months=item.warranty_months,
        weight_g=item.weight_g, params=item.params, content_hash=content_hash, last_seen_at=seen_at,
    )


def _match_unlinked(chunk: list, known: dict) -> dict:
    unlinked = [item for item in chunk
                if (old := known.get(item.external_id)) is None or old.product_id is None]
    return dict(zip((item.external_id for item in unlinked), match_offers(unlinked)))


def _write_chunk(shop, chunk: list, seen_at, stats: WriteStats) -> None:
    known = {
        external_id: KnownOffer(pk, content_hash, price, in_stock, product_id)
        for external_id, pk, content_hash, price, in_stock, product_id in Offer.objects
        .filter(shop=shop, external_id__in=[item.external_id for item in chunk])
        .values_list("external_id", "pk", "content_hash", "price", "in_stock", "product_id")
    }
    product_ids = _match_unlinked(chunk, known)
    created, changed, unchanged_ids, history, linked = [], [], [], [], []

    for item in chunk:
        content_hash = item.content_hash()
        old = known.get(item.external_id)
        if old is None:
            created.append(_new_offer(shop, item, content_hash, seen_at, product_ids.get(item.external_id)))
            continue
        pk, old_hash, old_price, old_in_stock, old_product_id = old
        if old_product_id is None and product_ids.get(item.external_id) is not None:
            linked.append(Offer(pk=pk, product_id=product_ids[item.external_id]))
        if old_hash == content_hash:
            unchanged_ids.append(pk)
            continue
        changed.append(_new_offer(shop, item, content_hash, seen_at))
        if (old_price, old_in_stock) != (item.price, item.in_stock):
            history.append(PriceHistory(offer_id=pk, price=item.price, in_stock=item.in_stock))

    if created or changed:
        to_save = created + changed
        Offer.objects.bulk_create(to_save, update_conflicts=True, unique_fields=["shop", "external_id"],
                                  update_fields=UPDATE_FIELDS)
        _fill_missing_pks(shop, created)
        history += [PriceHistory(offer_id=offer.pk, price=offer.price, in_stock=offer.in_stock) for offer in created]
    if linked:
        Offer.objects.bulk_update(linked, ["product"])
    if unchanged_ids:
        Offer.objects.filter(pk__in=unchanged_ids).update(last_seen_at=seen_at)
    PriceHistory.objects.bulk_create(history)

    stats.created += len(created)
    stats.updated += len(changed)
    stats.unchanged += len(unchanged_ids)


def _fill_missing_pks(shop, offers: list) -> None:
    missing = [offer for offer in offers if offer.pk is None]
    if missing:
        ids = dict(Offer.objects.filter(shop=shop, external_id__in=[o.external_id for o in missing])
                   .values_list("external_id", "pk"))
        for offer in missing:
            offer.pk = ids[offer.external_id]


def write_offers(shop, offers: Iterable[NormalizedOffer], seen_at, chunk_size: int = CHUNK_SIZE) -> WriteStats:
    stats = WriteStats()
    with transaction.atomic():
        for chunk in _chunks(offers, chunk_size):
            _write_chunk(shop, chunk, seen_at, stats)
    return stats