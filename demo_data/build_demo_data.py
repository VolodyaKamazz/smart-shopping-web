#!/usr/bin/env python3
"""Сборка демо-данных «Умного Шопинга».

Запуск из корня проекта:  python demo_data/build_demo_data.py

Что делает (результат детерминирован, повторный запуск даёт те же файлы):
  1. Читает справочник городов (demo_data/source/hflabs_city.csv, hflabs/city).
  2. Выбирает города с населением от 400 тыс., назначает каждому зону
     (ближайший из 10 узлов-хабов) -> demo_data/cities.json, zones.json.
  3. Строит матрицу ZoneRate: цена = тариф ФАС (Почта России, приказ № 104/26)
     за 500 г для тарифного пояса, определённого по расстоянию между хабами,
     умноженный на число полных/неполных 500 г и на НДС 22% -> zone_rates.json.
  4. Записывает категории, бренды, магазины (categories.json, brands.json, shops.json).
  5. Генерирует три YML-фида магазинов -> static/demo_feeds/*.yml.

Реальные данные: города, регионы, координаты, население, тарифы ФАС, модели
товаров. Тестовые значения (помечены в SOURCES.md): цены и наличие в фидах,
рейтинги магазинов, правила доставки магазинов, сроки доставки по поясам,
вес с упаковкой.
"""
import csv
import json
import math
import random
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "demo_data"
FEEDS = ROOT / "static" / "demo_feeds"

MIN_POPULATION = 400_000
FEED_DATE = "2026-10-29 12:00"
VAT = Decimal("1.22")  # НДС 22% (268,40 = 220 * 1,22; тарифы Почты России с марта 2026)

# --- Зоны: узлы-хабы (zone -> город). Город получает зону ближайшего хаба. ---------
HUBS = {
    1: "Москва",
    2: "Санкт-Петербург",
    3: "Ростов-на-Дону",
    4: "Нижний Новгород",
    5: "Самара",
    6: "Екатеринбург",
    7: "Новосибирск",
    8: "Красноярск",
    9: "Иркутск",
    10: "Хабаровск",
}

# Приказ ФАС России от 24.02.2026 № 104/26, п. 3.1: плата за каждые полные или
# неполные 500 г бандероли с объявленной ценностью (наземный транспорт), без НДС.
FAS_BELTS = [  # (макс. расстояние, км; пояс; ₽ без НДС за 500 г)
    (600, 1, Decimal("220.00")),
    (2000, 2, Decimal("240.00")),
    (5000, 3, Decimal("260.00")),
    (8000, 4, Decimal("295.00")),
    (10 ** 9, 5, Decimal("330.00")),
]
WEIGHT_CLASSES_KG = [Decimal("0.5"), Decimal("1"), Decimal("2"), Decimal("3"), Decimal("5")]
# Сроки в приказе ФАС не публикуются, это ОЦЕНКА (min, max дней) по поясу.
BELT_DAYS = {1: (2, 5), 2: (3, 7), 3: (6, 12), 4: (9, 16), 5: (12, 20)}


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def belt_for(distance_km):
    d = round(distance_km)
    for limit, belt, rate in FAS_BELTS:
        if d <= limit:
            return belt, rate
    raise AssertionError


# --- Города ---------------------------------------------------------------------
REGION_OVERRIDES = {
    "Кемеровская область - Кузбасс": "Кемеровская область — Кузбасс",
    "Саха /Якутия/": "Республика Саха (Якутия)",
}


def region_title(row):
    rt, name = row["region_type"], row["region"]
    if name in REGION_OVERRIDES:
        return REGION_OVERRIDES[name]
    if rt == "г":
        return name
    if rt == "Чувашия":
        return name
    if rt == "обл":
        return f"{name} область"
    if rt == "край":
        return f"{name} край"
    if rt == "Респ":
        return f"{name} Республика" if name.endswith("ая") else f"Республика {name}"
    return f"{rt} {name}"


def load_cities():
    with open(DATA / "source" / "hflabs_city.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["population"]]
    rows = [r for r in rows if int(r["population"]) >= MIN_POPULATION]
    rows.sort(key=lambda r: -int(r["population"]))
    cities = []
    for r in rows:
        region = region_title(r)
        name = r["city"] or r["region"]  # Москва, Санкт-Петербург: город = регион
        cities.append({
            "name": name,
            "region": region,
            "federal_district": r["federal_district"],
            "lat": float(r["geo_lat"]),
            "lon": float(r["geo_lon"]),
            "population": int(r["population"]),
        })
    return cities


def build_geo():
    cities = load_cities()
    by_name = {c["name"]: c for c in cities}
    hubs = {z: by_name[n] for z, n in HUBS.items()}
    for c in cities:
        c["zone"] = min(hubs, key=lambda z: haversine_km(c["lat"], c["lon"], hubs[z]["lat"], hubs[z]["lon"]))
    zones = []
    for z, hub in hubs.items():
        members = [c["name"] for c in cities if c["zone"] == z]
        zones.append({"zone": z, "hub": hub["name"], "cities": members})
    rates = []
    for zf, hf in hubs.items():
        for zt, ht in hubs.items():
            dist = 0 if zf == zt else haversine_km(hf["lat"], hf["lon"], ht["lat"], ht["lon"])
            belt, rate = belt_for(dist)
            dmin, dmax = BELT_DAYS[belt]
            for w in WEIGHT_CLASSES_KG:
                steps = int((w / Decimal("0.5")).to_integral_value(rounding="ROUND_CEILING"))
                price = (rate * steps * VAT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                rates.append({
                    "zone_from": zf, "zone_to": zt, "max_weight_kg": str(w),
                    "price": str(price), "min_days": dmin, "max_days": dmax,
                    "belt": belt, "hub_distance_km": round(dist),
                })
    return cities, zones, rates


# --- Категории, бренды -------------------------------------------------------------
CATEGORIES = [
    {"slug": "electronics", "name": "Электроника", "parent": None,
     "keywords": "электроника, техника, гаджет, гаджеты"},
    {"slug": "smartphones", "name": "Смартфоны", "parent": "electronics",
     "keywords": "смартфон, смартфоны, телефон, телефоны, мобильный, мобильник, сотовый"},
    {"slug": "laptops", "name": "Ноутбуки", "parent": "electronics",
     "keywords": "ноутбук, ноутбуки, ультрабук, лэптоп, макбук"},
    {"slug": "tablets", "name": "Планшеты", "parent": "electronics",
     "keywords": "планшет, планшеты, планшетный компьютер, айпад"},
    {"slug": "headphones", "name": "Наушники", "parent": "electronics",
     "keywords": "наушники, наушник, гарнитура, беспроводные наушники, tws, вкладыши"},
]

BRANDS = ["Apple", "Samsung", "Xiaomi", "POCO", "Honor", "Huawei", "OPPO", "vivo",
          "Lenovo", "ASUS", "HP", "Acer", "Sony", "JBL"]


def norm_brand(name):
    return " ".join("".join(ch if ch.isalnum() else " " for ch in name.lower()).split())


# --- Товары фидов -------------------------------------------------------------------
# cat: slug; type: typePrefix; vendor; model; code: vendorCode (только если известен
# производителем); params: (название, значение, единица); base: ТЕСТОВАЯ базовая цена, ₽;
# kg: ТЕСТОВЫЙ вес с упаковкой; shops: в каких фидах есть товар.
CL, DN, DR = "citilink", "dns", "2droida"
ALL = (CL, DN, DR)
PRODUCTS = [
    # смартфоны
    dict(cat="smartphones", type="Смартфон", vendor="Samsung", model="Galaxy S24 8/256GB", code="SM-S921B",
         params=[("Диагональ экрана", "6.2", "дюйм"), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=64990, kg=0.45, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Samsung", model="Galaxy S24+ 12/512GB", code="SM-S926B",
         params=[("Диагональ экрана", "6.7", "дюйм"), ("Оперативная память", "12", "ГБ"), ("Встроенная память", "512", "ГБ")],
         base=84990, kg=0.5, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Samsung", model="Galaxy A55 5G 8/256GB", code="SM-A556B",
         params=[("Диагональ экрана", "6.6", "дюйм"), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=32990, kg=0.45, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Apple", model="iPhone 15 128GB", code="",
         params=[("Диагональ экрана", "6.1", "дюйм"), ("Встроенная память", "128", "ГБ")],
         base=69990, kg=0.4, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Apple", model="iPhone 15 Pro 256GB", code="",
         params=[("Диагональ экрана", "6.1", "дюйм"), ("Встроенная память", "256", "ГБ")],
         base=94990, kg=0.4, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Xiaomi", model="Redmi Note 13 Pro 8/256GB", code="",
         params=[("Диагональ экрана", "6.67", "дюйм"), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=24990, kg=0.45, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Xiaomi", model="14T 12/256GB", code="",
         params=[("Диагональ экрана", "6.67", "дюйм"), ("Оперативная память", "12", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=44990, kg=0.45, shops=ALL),
    dict(cat="smartphones", type="Смартфон", vendor="Honor", model="200 12/512GB", code="",
         params=[("Диагональ экрана", "6.7", "дюйм"), ("Оперативная память", "12", "ГБ"), ("Встроенная память", "512", "ГБ")],
         base=39990, kg=0.45, shops=(DN, DR)),
    # ноутбуки
    dict(cat="laptops", type="Ноутбук", vendor="Apple", model="MacBook Air 13 M2 8/256GB", code="",
         params=[("Диагональ экрана", "13.6", "дюйм"), ("Процессор", "Apple M2", ""), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=99990, kg=2.0, shops=ALL),
    dict(cat="laptops", type="Ноутбук", vendor="Apple", model="MacBook Air 15 M2 8/256GB", code="",
         params=[("Диагональ экрана", "15.3", "дюйм"), ("Процессор", "Apple M2", ""), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=124990, kg=2.5, shops=(CL, DR)),
    dict(cat="laptops", type="Ноутбук", vendor="Lenovo", model="IdeaPad Slim 3 15IAH8", code="15IAH8",
         params=[("Диагональ экрана", "15.6", "дюйм"), ("Процессор", "Intel Core i5-12450H", "")],
         base=54990, kg=3.0, shops=ALL),
    # планшеты
    dict(cat="tablets", type="Планшет", vendor="Apple", model="iPad 10.9 (10-го поколения) Wi-Fi 64GB", code="",
         params=[("Диагональ экрана", "10.9", "дюйм"), ("Встроенная память", "64", "ГБ")],
         base=42990, kg=0.9, shops=ALL),
    dict(cat="tablets", type="Планшет", vendor="Samsung", model="Galaxy Tab A9+ Wi-Fi 4/64GB", code="SM-X210",
         params=[("Диагональ экрана", "11", "дюйм"), ("Оперативная память", "4", "ГБ"), ("Встроенная память", "64", "ГБ")],
         base=19990, kg=0.8, shops=ALL),
    dict(cat="tablets", type="Планшет", vendor="Xiaomi", model="Pad 6 8/256GB", code="",
         params=[("Диагональ экрана", "11", "дюйм"), ("Оперативная память", "8", "ГБ"), ("Встроенная память", "256", "ГБ")],
         base=34990, kg=0.9, shops=(CL, DN)),
    # наушники
    dict(cat="headphones", type="Наушники", vendor="Apple", model="AirPods Pro (2-го поколения) USB-C", code="",
         params=[("Тип", "TWS (вкладыши)", ""), ("Шумоподавление", "Активное", ""), ("Подключение", "Bluetooth", "")],
         base=24990, kg=0.25, shops=ALL),
    dict(cat="headphones", type="Наушники", vendor="Sony", model="WH-1000XM5", code="WH-1000XM5",
         params=[("Тип", "Полноразмерные", ""), ("Шумоподавление", "Активное", ""), ("Подключение", "Bluetooth", "")],
         base=29990, kg=0.9, shops=ALL),
    dict(cat="headphones", type="Наушники", vendor="JBL", model="Tune 520BT", code="",
         params=[("Тип", "Накладные", ""), ("Подключение", "Bluetooth", "")],
         base=4990, kg=0.4, shops=ALL),
    dict(cat="headphones", type="Наушники", vendor="Samsung", model="Galaxy Buds2 Pro", code="SM-R510",
         params=[("Тип", "TWS (вкладыши)", ""), ("Шумоподавление", "Активное", ""), ("Подключение", "Bluetooth", "")],
         base=14990, kg=0.2, shops=(DR,)),
]

# Базовые коэффициенты цены по магазинам (тестовые).
PRICE_FACTOR = {CL: 1.00, DN: 0.97, DR: 1.03}

SHOPS = [
    {
        "key": CL, "name": "Ситилинк", "url": "https://www.citilink.ru", "origin_city": "Москва",
        "rating": "4.70", "rating_count": 18450, "return_days": 7, "warranty_months": 12,
        "payment_methods": ["card_online", "card_on_receipt", "cash", "sbp"],
        "refresh_hours": 6, "feed_file": "citilink.yml", "style": "vendor.model",
        "cat_ids": {"smartphones": 11, "laptops": 12, "tablets": 13, "headphones": 14, "electronics": 1},
        "search_url": "https://www.citilink.ru/search/?text={q}", "id_prefix": "CL",
        "delivery_rules": [
            {"city": None, "cost": "499.00", "free_from": "7000.00", "min_days": 2, "max_days": 6},
            {"city": "Москва", "cost": "299.00", "free_from": "5000.00", "min_days": 1, "max_days": 2},
            {"city": "Санкт-Петербург", "cost": "349.00", "free_from": "5000.00", "min_days": 1, "max_days": 3},
        ],
    },
    {
        "key": DN, "name": "DNS", "url": "https://www.dns-shop.ru", "origin_city": "Москва",
        "rating": "4.60", "rating_count": 9210, "return_days": 7, "warranty_months": 12,
        "payment_methods": ["card_online", "card_on_receipt", "cash"],
        "refresh_hours": 6, "feed_file": "dns.yml", "style": "name",
        "cat_ids": {"smartphones": 101, "laptops": 102, "tablets": 103, "headphones": 104, "electronics": 100},
        "search_url": "https://www.dns-shop.ru/search/?q={q}", "id_prefix": "DN",
        "delivery_rules": [
            {"city": None, "cost": "399.00", "free_from": "10000.00", "min_days": 3, "max_days": 8},
            {"city": "Москва", "cost": "199.00", "free_from": "3000.00", "min_days": 1, "max_days": 2},
            {"city": "Новосибирск", "cost": "349.00", "free_from": "10000.00", "min_days": 2, "max_days": 4},
        ],
    },
    {
        "key": DR, "name": "2DROIDA", "url": "https://2droida.ru", "origin_city": "Москва",
        # мало оценок при высоком рейтинге: проверка байесовской надёжности (неделя 3)
        "rating": "4.90", "rating_count": 14, "return_days": 7, "warranty_months": 12,
        "payment_methods": ["card_online", "cash", "sbp"],
        "refresh_hours": 12, "feed_file": "2droida.yml", "style": "vendor.model",
        "cat_ids": {"smartphones": 5001, "laptops": 5002, "tablets": 5003, "headphones": 5004, "electronics": 5000},
        # реальные разделы каталога 2droida.ru
        "section_urls": {"smartphones": "https://2droida.ru/catalog/smartfony/",
                         "laptops": "https://2droida.ru/catalog/noutbuki/",
                         "tablets": "https://2droida.ru/catalog/planshety/",
                         "headphones": "https://2droida.ru/catalog/naushniki-i-garnitury/"},
        "id_prefix": "DR",
        "delivery_rules": [
            {"city": None, "cost": "600.00", "free_from": "15000.00", "min_days": 3, "max_days": 9},
            {"city": "Москва", "cost": "300.00", "free_from": "5000.00", "min_days": 1, "max_days": 2},
            {"city": "Новосибирск", "cost": "250.00", "free_from": "3000.00", "min_days": 1, "max_days": 2},
            {"city": "Томск", "cost": "250.00", "free_from": "3000.00", "min_days": 1, "max_days": 2},
            {"city": "Кемерово", "cost": "250.00", "free_from": "3000.00", "min_days": 1, "max_days": 2},
        ],
    },
]

CATEGORY_NAMES = {c["slug"]: c["name"] for c in CATEGORIES}
FEED_URL_TEMPLATE = "http://127.0.0.1:8000/static/demo_feeds/{}"


def round_price(x):
    return int(round(x / 100.0) * 100 - 10)  # цены вида 12 990


def offer_url(shop, prod):
    if shop["key"] == DR:
        return shop["section_urls"][prod["cat"]]
    from urllib.parse import quote
    return shop["search_url"].format(q=quote(f'{prod["vendor"]} {prod["model"]}'))


def build_offers():
    """Список офферов по магазинам (детерминированно)."""
    rnd = random.Random(20261029)
    result = {s["key"]: [] for s in SHOPS}
    counters = {s["key"]: 0 for s in SHOPS}
    for prod in PRODUCTS:
        for shop in SHOPS:
            if shop["key"] not in prod["shops"]:
                continue
            counters[shop["key"]] += 1
            jitter = 1 + rnd.uniform(-0.03, 0.03)
            price = round_price(prod["base"] * PRICE_FACTOR[shop["key"]] * jitter)
            old = round_price(price * 1.08) if rnd.random() < 0.25 else None
            available = rnd.random() > 0.12
            result[shop["key"]].append({
                "id": f'{shop["id_prefix"]}{1000 + counters[shop["key"]]}',
                "prod": prod, "price": price, "old": old, "available": available,
            })
    return result


def sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def build_feed(shop, offers):
    root = ET.Element("yml_catalog", date=FEED_DATE)
    sh = sub(root, "shop")
    sub(sh, "name", shop["name"])
    sub(sh, "company", shop["name"])
    sub(sh, "url", shop["url"])
    cur = sub(sh, "currencies")
    sub(cur, "currency", id="RUR", rate=1)
    cats = sub(sh, "categories")
    ids = shop["cat_ids"]
    sub(cats, "category", CATEGORY_NAMES["electronics"], id=ids["electronics"])
    for slug in ("smartphones", "laptops", "tablets", "headphones"):
        sub(cats, "category", CATEGORY_NAMES[slug], id=ids[slug], parentId=ids["electronics"])
    off = sub(sh, "offers")

    def one(o):
        prod = o["prod"]
        attrs = {"id": o["id"], "available": "true" if o["available"] else "false"}
        if shop["style"] == "vendor.model":
            attrs["type"] = "vendor.model"
        e = sub(off, "offer", **attrs)
        sub(e, "url", offer_url(shop, prod))
        sub(e, "price", o["price"])
        if o["old"]:
            sub(e, "oldprice", o["old"])
        sub(e, "currencyId", "RUR")
        sub(e, "categoryId", ids[prod["cat"]])
        if shop["style"] == "vendor.model":
            sub(e, "typePrefix", prod["type"])
            sub(e, "vendor", prod["vendor"])
            sub(e, "model", prod["model"])
        else:
            title = f'{prod["type"]} {prod["vendor"]} {prod["model"]}'
            if prod["code"]:
                title += f' ({prod["code"]})'
            sub(e, "name", title)
            sub(e, "vendor", prod["vendor"])
        if prod["code"]:
            sub(e, "vendorCode", prod["code"])
        sub(e, "manufacturer_warranty", "true")
        sub(e, "warranty-days", "P1Y")
        # DNS не передаёт вес ноутбуков: проверка запасного веса по классу категории
        if not (shop["key"] == DN and prod["cat"] == "laptops"):
            sub(e, "weight", f'{prod["kg"]:.3f}')
        for name, value, unit in prod["params"]:
            if unit:
                sub(e, "param", value, name=name, unit=unit)
            else:
                sub(e, "param", value, name=name)
        return e

    for o in offers:
        one(o)
    return root


def add_anomalies(shop, root):
    """Намеренно некорректные записи: импорт должен их пропускать (неделя 2)."""
    off = root.find("shop/offers")
    ids = shop["cat_ids"]

    def broken(oid, **kw):
        e = sub(off, "offer", id=oid, available="true", type="vendor.model")
        sub(e, "url", shop["url"])
        if "price" in kw:
            sub(e, "price", kw["price"])
        sub(e, "currencyId", "RUR")
        sub(e, "categoryId", kw.get("categoryId", ids["smartphones"]))
        sub(e, "typePrefix", "Смартфон")
        sub(e, "vendor", "Xiaomi")
        sub(e, "model", "14T 12/256GB")
    if shop["key"] == DN:
        broken("DN-ERR-1")  # нет цены
        broken("DN-ERR-2", price=44990, categoryId=999999)  # категории нет в фиде
    if shop["key"] == DR:
        broken("DR-ERR-1", price="abc")  # цена не число


def write_feed(shop, root):
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    head = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE yml_catalog SYSTEM "shops.dtd">\n'
    (FEEDS / shop["feed_file"]).write_text(head + body + "\n", encoding="utf-8")


def dump(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    FEEDS.mkdir(parents=True, exist_ok=True)
    cities, zones, rates = build_geo()
    dump("cities.json", cities)
    dump("zones.json", zones)
    dump("zone_rates.json", rates)
    dump("categories.json", CATEGORIES)
    dump("brands.json", [{"name": b, "normalized_name": norm_brand(b)} for b in BRANDS])

    offers = build_offers()
    shops_json = []
    for shop in SHOPS:
        root = build_feed(shop, offers[shop["key"]])
        add_anomalies(shop, root)
        write_feed(shop, root)
        slug_by_id = {str(v): k for k, v in shop["cat_ids"].items()}
        shops_json.append({
            "name": shop["name"], "url": shop["url"], "origin_city": shop["origin_city"],
            "rating": shop["rating"], "rating_count": shop["rating_count"],
            "return_days": shop["return_days"], "warranty_months": shop["warranty_months"],
            "payment_methods": shop["payment_methods"], "refresh_hours": shop["refresh_hours"],
            "feed_url": FEED_URL_TEMPLATE.format(shop["feed_file"]),
            "category_map": slug_by_id,
            "delivery_rules": shop["delivery_rules"],
        })
    dump("shops.json", shops_json)
    for s in SHOPS:
        n = len(offers[s["key"]])
        print(f'{s["name"]}: {n} предложений + аномалий: '
              f'{ {CL: 0, DN: 2, DR: 1}[s["key"]] }')
    print("города:", len(cities), "| ZoneRate:", len(rates))


if __name__ == "__main__":
    main()