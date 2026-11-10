import hashlib
import json
import re
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from .yml_parser import RawOffer

CENT = Decimal("0.01")
MAX_PRICE = Decimal("10000000000")
MAX_WEIGHT_G = 1_000_000_000
MAX_WARRANTY_MONTHS = 1200
MAX_EXTERNAL_ID_LEN = 100
MAX_URL_LEN = 2048
MAX_TITLE_LEN = 500

RUB_CODES = {"RUR", "RUB"}
FALSE_VALUES = {"false", "0", "no", "нет", "-", "\u2212"}
NUMBER_RE = re.compile(r"\d+(\.\d+)?")
DURATION_RE = re.compile(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T.*)?")


class InvalidOffer(Exception):
    """Предложение нельзя загрузить. Текст исключения — причина для лога."""


@dataclass(frozen=True)
class NormalizedOffer:
    external_id: str
    url: str
    title: str
    price: Decimal
    old_price: Decimal | None
    in_stock: bool
    warranty_months: int | None
    weight_g: int | None
    params: dict
    category_slug: str
    vendor: str
    model: str
    vendor_code: str
    barcodes: tuple

    def content_hash(self) -> str:
        values = [getattr(self, name) for name in _HASHED_FIELDS]
        payload = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_HASHED_FIELDS = tuple(field.name for field in fields(NormalizedOffer))


def _clean(text: str) -> str:
    return " ".join(text.split())


def _parse_number(text: str) -> Decimal | None:
    text = text.replace(",", ".")
    return Decimal(text) if NUMBER_RE.fullmatch(text) else None


def _parse_price(text: str) -> Decimal:
    if not text:
        raise InvalidOffer("нет цены")
    price = _parse_number(text)
    if price is None:
        raise InvalidOffer(f"цена не число: {text!r}")
    price = price.quantize(CENT, rounding=ROUND_HALF_UP)
    if price <= 0 or price >= MAX_PRICE:
        raise InvalidOffer(f"цена вне допустимых границ: {text!r}")
    return price


def _parse_old_price(text: str, price: Decimal) -> Decimal | None:
    old_price = _parse_number(text) if text else None
    if old_price is None:
        return None
    old_price = old_price.quantize(CENT, rounding=ROUND_HALF_UP)
    return old_price if price < old_price < MAX_PRICE else None


def _parse_in_stock(text: str) -> bool:
    return text.lower() not in FALSE_VALUES


def _parse_warranty_months(text: str) -> int | None:
    match = DURATION_RE.fullmatch(text)
    if not match or not any(match.groups()):
        return None
    years, months, weeks, days = (int(part or 0) for part in match.groups())
    total = years * 12 + months + (weeks * 7 + days + 15) // 30
    return total if 0 < total <= MAX_WARRANTY_MONTHS else None


def _parse_weight_g(text: str) -> int | None:
    kilograms = _parse_number(text) if text else None
    if kilograms is None:
        return None
    grams = int((kilograms * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    return grams if 0 < grams <= MAX_WEIGHT_G else None


def _parse_params(raw_params: list) -> dict:
    params = {}
    for name, unit, value in raw_params:
        name, value = _clean(name), _clean(value)
        if name and value:
            params.setdefault(name, {"value": value, "unit": _clean(unit)})
    return params


def _check_url(url: str) -> str:
    if not url:
        raise InvalidOffer("нет url")
    try:
        parsed = urlparse(url)
    except ValueError:
        raise InvalidOffer(f"некорректный url: {url!r}") from None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidOffer(f"url не http/https или без адреса сайта: {url!r}")
    if len(url) > MAX_URL_LEN:
        raise InvalidOffer(f"url длиннее {MAX_URL_LEN} символов")
    return url


def _model_from_name(name: str, vendor: str, vendor_code: str) -> str:
    found = re.search(rf"(?<!\w){re.escape(vendor)}(?!\w)", name, re.IGNORECASE)
    model = name[found.end():].strip() if found else name
    suffix = f"({vendor_code})"
    if vendor_code and model.lower().endswith(suffix.lower()):
        model = model[:-len(suffix)].rstrip()
    return model or name


def _title_and_model(raw: RawOffer, vendor: str) -> tuple:
    if raw.type == "vendor.model":
        model = _clean(raw.model)
        if not model:
            raise InvalidOffer("нет модели")
        return _clean(" ".join(part for part in (raw.type_prefix, vendor, model) if part)), model
    name = _clean(raw.name)
    if not name:
        raise InvalidOffer("нет названия")
    return name, _model_from_name(name, vendor, _clean(raw.vendor_code))


def normalize_offer(raw: RawOffer, category_map: dict) -> NormalizedOffer:
    if not raw.id:
        raise InvalidOffer("нет id")
    if len(raw.id) > MAX_EXTERNAL_ID_LEN:
        raise InvalidOffer("id длиннее 100 символов")
    price = _parse_price(raw.price)
    if raw.currency_id.upper() not in RUB_CODES:
        raise InvalidOffer(f"валюта не рубли: {raw.currency_id!r}")
    category_slug = category_map.get(raw.category_id)
    if category_slug is None:
        raise InvalidOffer(f"категория {raw.category_id!r} не сопоставлена")
    vendor = _clean(raw.vendor)
    if not vendor:
        raise InvalidOffer("нет производителя")
    title, model = _title_and_model(raw, vendor)
    url = _check_url(raw.url)

    return NormalizedOffer(
        external_id=raw.id,
        url=url,
        title=title[:MAX_TITLE_LEN],
        price=price,
        old_price=_parse_old_price(raw.oldprice, price),
        in_stock=_parse_in_stock(raw.available),
        warranty_months=_parse_warranty_months(raw.warranty_days),
        weight_g=_parse_weight_g(raw.weight),
        params=_parse_params(raw.params),
        category_slug=category_slug,
        vendor=vendor,
        model=model,
        vendor_code=_clean(raw.vendor_code),
        barcodes=tuple(dict.fromkeys(raw.barcodes)),
    )