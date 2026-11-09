from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO
from xml.etree.ElementTree import Element, iterparse


@dataclass(frozen=True)
class RawOffer:
    id: str = ""
    available: str = ""
    type: str = ""
    url: str = ""
    price: str = ""
    oldprice: str = ""
    currency_id: str = ""
    category_id: str = ""
    type_prefix: str = ""
    vendor: str = ""
    model: str = ""
    name: str = ""
    vendor_code: str = ""
    warranty_days: str = ""
    weight: str = ""
    params: list = field(default_factory=list)
    barcodes: list = field(default_factory=list)


def _text(offer: Element, tag: str) -> str:
    return (offer.findtext(tag) or "").strip()


def _barcodes(offer: Element) -> list:
    codes = (code.strip() for node in offer.findall("barcode") for code in (node.text or "").split(","))
    return [code for code in codes if code]


def _raw_offer(offer: Element) -> RawOffer:
    return RawOffer(
        id=(offer.get("id") or "").strip(),
        available=(offer.get("available") or "").strip(),
        type=(offer.get("type") or "").strip(),
        url=_text(offer, "url"),
        price=_text(offer, "price"),
        oldprice=_text(offer, "oldprice"),
        currency_id=_text(offer, "currencyId"),
        category_id=_text(offer, "categoryId"),
        type_prefix=_text(offer, "typePrefix"),
        vendor=_text(offer, "vendor"),
        model=_text(offer, "model"),
        name=_text(offer, "name"),
        vendor_code=_text(offer, "vendorCode"),
        warranty_days=_text(offer, "warranty-days"),
        weight=_text(offer, "weight"),
        params=[(param.get("name") or "", param.get("unit") or "", param.text or "")
                for param in offer.findall("param")],
        barcodes=_barcodes(offer),
    )


def iter_offers(feed: IO[bytes]) -> Iterator[RawOffer]:
    open_nodes = []
    for event, node in iterparse(feed, events=("start", "end")):
        if event == "start":
            open_nodes.append(node)
            continue
        open_nodes.pop()
        if node.tag == "offer":
            yield _raw_offer(node)
            node.clear()
            if open_nodes:
                open_nodes[-1].remove(node)