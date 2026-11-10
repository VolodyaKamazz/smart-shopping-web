from itertools import count

import httpx
from django.conf import settings

from catalog.models import Shop
from importer.models import ImportRun
from importer.normalizer import NormalizedOffer, normalize_offer
from importer.services import import_shop
from importer.yml_parser import RawOffer

FEEDS_DIR = settings.DEMO_FEEDS_DIR


def demo_feed(name: str) -> bytes:
    return (FEEDS_DIR / name).read_bytes()


def make_client(routes: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        result = routes[str(request.url)]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, int):
            return httpx.Response(result)
        return httpx.Response(200, content=result)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def offer_xml(offer_id="1", **tags) -> str:
    fields = {
        "url": "https://shop.example/p/1", "price": "1000", "currencyId": "RUR", "categoryId": "10",
        "typePrefix": "Смартфон", "vendor": "Samsung", "model": "Galaxy S24 8/256GB",
        "vendorCode": "SM-S921B",
    }
    fields.update(tags)
    body = "".join(f"<{tag}>{value}</{tag}>" for tag, value in fields.items() if value is not None)
    return f'<offer id="{offer_id}" type="vendor.model" available="true">{body}</offer>'


def feed_xml(*offers: str, encoding="UTF-8") -> bytes:
    xml = (f'<?xml version="1.0" encoding="{encoding}"?><yml_catalog date="2026-11-04T12:00:00+03:00">'
           f'<shop><offers>{"".join(offers)}</offers></shop></yml_catalog>')
    return xml.encode(encoding)


CATEGORY_MAP = {"10": "smartphones", "1": "electronics"}


def raw(**fields) -> RawOffer:
    data = dict(id="A1", available="true", type="vendor.model", url="https://shop.example/p/1",
                price="62890", currency_id="RUR", category_id="10", type_prefix="Смартфон",
                vendor="Samsung", model="Galaxy S24 8/256GB", vendor_code="SM-S921B")
    data.update(fields)
    return RawOffer(**data)


def normalize(**fields) -> NormalizedOffer:
    return normalize_offer(raw(**fields), CATEGORY_MAP)


_shop_numbers = count(1)


def make_shop(name="Магазин", **fields) -> Shop:
    fields.setdefault("feed_url", f"http://shop{next(_shop_numbers)}.example/feed.yml")
    fields.setdefault("category_map", {"10": "smartphones"})
    return Shop.objects.create(name=name, **fields)


def do_import(shop: Shop, response) -> ImportRun:
    with make_client({shop.feed_url: response}) as client:
        return import_shop(shop, client)


def many_offers_feed(count_: int, **tags) -> bytes:
    return feed_xml(*(offer_xml(str(i), **tags) for i in range(count_)))
