from dataclasses import fields, replace
from decimal import Decimal

from django.test import SimpleTestCase

from importer.normalizer import InvalidOffer, NormalizedOffer

from .helpers import normalize


class ValidOfferTests(SimpleTestCase):
    def test_full_offer(self):
        offer = normalize(oldprice="67890", warranty_days="P1Y", weight="0.450",
                          barcodes=["4006381333931"], params=[("Диагональ экрана", "дюйм", "6.2")])
        self.assertEqual(offer.external_id, "A1")
        self.assertEqual(offer.title, "Смартфон Samsung Galaxy S24 8/256GB")
        self.assertEqual(offer.price, Decimal("62890.00"))
        self.assertEqual(offer.old_price, Decimal("67890.00"))
        self.assertTrue(offer.in_stock)
        self.assertEqual(offer.warranty_months, 12)
        self.assertEqual(offer.weight_g, 450)
        self.assertEqual(offer.params, {"Диагональ экрана": {"value": "6.2", "unit": "дюйм"}})
        self.assertEqual(offer.category_slug, "smartphones")
        self.assertEqual((offer.vendor, offer.model, offer.vendor_code), ("Samsung", "Galaxy S24 8/256GB", "SM-S921B"))
        self.assertEqual(offer.barcodes, ("4006381333931",))

    def test_optional_fields_may_be_absent(self):
        offer = normalize()
        self.assertIsNone(offer.old_price)
        self.assertIsNone(offer.warranty_months)
        self.assertIsNone(offer.weight_g)
        self.assertEqual(offer.params, {})
        self.assertEqual(offer.barcodes, ())

    def test_duplicate_barcodes_are_collapsed_keeping_order(self):
        self.assertEqual(normalize(barcodes=["2", "1", "2"]).barcodes, ("2", "1"))


class PriceTests(SimpleTestCase):
    def test_accepted_formats(self):
        cases = {"1000": "1000.00", "999.5": "999.50", "999,5": "999.50", "0.005": "0.01",
                 "12.345": "12.35", "9999999999.99": "9999999999.99"}
        for text, expected in cases.items():
            with self.subTest(price=text):
                self.assertEqual(normalize(price=text).price, Decimal(expected))

    def test_rejected_values(self):
        for text in ("", "abc", "-5", "0", "0.00", "0.004", "NaN", "Infinity", "1e5", "64 990", "1.2.3",
                     "10000000000", "99999999999999"):
            with self.subTest(price=text), self.assertRaises(InvalidOffer):
                normalize(price=text)

    def test_old_price_is_dropped_when_not_useful(self):
        for text in ("abc", "-1", "62890", "50000", "NaN", "99999999999"):
            with self.subTest(oldprice=text):
                self.assertIsNone(normalize(oldprice=text).old_price)

    def test_old_price_above_price_is_kept(self):
        self.assertEqual(normalize(oldprice="62890,01").old_price, Decimal("62890.01"))


class CurrencyAndCategoryTests(SimpleTestCase):
    def test_rub_aliases_are_accepted(self):
        for code in ("RUR", "RUB", "rub"):
            with self.subTest(code=code):
                normalize(currency_id=code)

    def test_other_or_missing_currency_is_rejected(self):
        for code in ("USD", "EUR", "KZT", ""):
            with self.subTest(code=code), self.assertRaises(InvalidOffer):
                normalize(currency_id=code)

    def test_category_goes_through_category_map(self):
        self.assertEqual(normalize(category_id="1").category_slug, "electronics")

    def test_unmapped_or_missing_category_is_rejected(self):
        for category_id in ("999999", ""):
            with self.subTest(category_id=category_id), self.assertRaises(InvalidOffer):
                normalize(category_id=category_id)


class IdUrlVendorTests(SimpleTestCase):
    def test_id_required_and_limited(self):
        with self.assertRaises(InvalidOffer):
            normalize(id="")
        normalize(id="x" * 100)
        with self.assertRaises(InvalidOffer):
            normalize(id="x" * 101)

    def test_url_must_be_http_or_https(self):
        normalize(url="http://shop.example/p")
        for url in ("", "javascript:alert(1)", "ftp://shop.example/p", "/relative/path", "shop.example/p",
                    "http:/shop.example", "https://", "http://[::1"):
            with self.subTest(url=url), self.assertRaises(InvalidOffer):
                normalize(url=url)

    def test_url_length_limit(self):
        normalize(url="https://shop.example/" + "a" * 2027)  # ровно 2048
        with self.assertRaises(InvalidOffer):
            normalize(url="https://shop.example/" + "a" * 2028)

    def test_vendor_is_required(self):
        with self.assertRaises(InvalidOffer):
            normalize(vendor="  ")


class TitleAndModelTests(SimpleTestCase):
    def test_vendor_model_title_skips_missing_prefix(self):
        self.assertEqual(normalize(type_prefix="").title, "Samsung Galaxy S24 8/256GB")

    def test_whitespace_is_collapsed(self):
        offer = normalize(vendor="  Samsung ", model="Galaxy \n  S24", type_prefix="Смартфон  ")
        self.assertEqual(offer.title, "Смартфон Samsung Galaxy S24")
        self.assertEqual(offer.model, "Galaxy S24")

    def test_vendor_model_offer_requires_model(self):
        with self.assertRaises(InvalidOffer):
            normalize(model="")

    def test_long_title_is_truncated(self):
        self.assertEqual(len(normalize(model="М" * 600).title), 500)

    def test_simple_offer_takes_name_and_extracts_model(self):
        offer = normalize(type="", name="Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)", model="", type_prefix="")
        self.assertEqual(offer.title, "Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)")
        self.assertEqual(offer.model, "Galaxy S24 8/256GB")

    def test_simple_offer_requires_name(self):
        with self.assertRaises(InvalidOffer):
            normalize(type="", name="", model="")

    def test_model_matches_between_feed_styles(self):
        simple = normalize(type="", name="Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)", model="")
        structured = normalize()
        self.assertEqual(simple.model, structured.model)

    def test_model_extraction_edge_cases(self):
        cases = [
            ("Ноутбук HP 15s-fq5000 (6D7A1EA)", "HP", "6D7A1EA", "15s-fq5000"),
            ("Наушники Apple AirPods Pro 2", "Apple", "", "AirPods Pro 2"),
            ("Смартфон samsung Galaxy A55", "Samsung", "", "Galaxy A55"),
            ("Чехол Chipset Pro", "HP", "", "Чехол Chipset Pro"),
            ("Смартфон Galaxy S24", "Samsung", "", "Смартфон Galaxy S24"),
            ("Samsung", "Samsung", "", "Samsung"),
            ("Смартфон Samsung Galaxy S24 (SM-S921B)", "Samsung", "SM-X", "Galaxy S24 (SM-S921B)"),
        ]
        for name, vendor, code, expected in cases:
            with self.subTest(name=name):
                offer = normalize(type="", name=name, model="", vendor=vendor, vendor_code=code)
                self.assertEqual(offer.model, expected)


class StockWarrantyWeightTests(SimpleTestCase):
    def test_availability(self):
        cases = {"true": True, "": True, "yes": True, "1": True, "false": False, "FALSE": False,
                 "0": False, "no": False, "-": False, "нет": False, "Нет": False, "\u2212": False, "да": True}
        for text, expected in cases.items():
            with self.subTest(available=text):
                self.assertIs(normalize(available=text).in_stock, expected)

    def test_warranty_durations(self):
        cases = {"P1Y": 12, "P2Y": 24, "P6M": 6, "P1Y6M": 18, "P12M": 12, "P730D": 24, "P2W": None,
                 "P90D": 3, "P1Y2M10DT2H30M": 14, "P0D": None, "P14D": None, "": None, "1 год": None,
                 "P": None, "PT5H": None, "P9999Y": None}
        for text, expected in cases.items():
            with self.subTest(warranty=text):
                self.assertEqual(normalize(warranty_days=text).warranty_months, expected)

    def test_weight_kilograms_to_grams(self):
        cases = {"0.450": 450, "1": 1000, "2,5": 2500, "0.0004": None, "0": None, "-1": None, "abc": None,
                 "": None, "1000000.001": None}
        for text, expected in cases.items():
            with self.subTest(weight=text):
                self.assertEqual(normalize(weight=text).weight_g, expected)

    def test_weight_upper_bound_is_inclusive(self):
        self.assertEqual(normalize(weight="1000000").weight_g, 1_000_000_000)
        self.assertIsNone(normalize(weight="1000000.001").weight_g)


class ParamsTests(SimpleTestCase):
    def test_params_are_cleaned(self):
        offer = normalize(params=[(" Цвет ", "", " чёрный  матовый "), ("Вес", " г ", "5"),
                                  ("", "", "без названия"), ("Пустой", "", ""), ("Цвет", "", "белый")])
        self.assertEqual(offer.params, {"Цвет": {"value": "чёрный матовый", "unit": ""},
                                        "Вес": {"value": "5", "unit": "г"}})


class ContentHashTests(SimpleTestCase):
    def test_same_data_same_hash(self):
        first = normalize(params=[("Цвет", "", "чёрный"), ("Вес", "г", "5")])
        second = normalize(params=[("Вес", "г", "5"), ("Цвет", "", "чёрный")])
        self.assertEqual(first.content_hash(), second.content_hash())
        self.assertEqual(len(first.content_hash()), 64)

    def test_every_field_changes_the_hash(self):
        base = dict(oldprice="70000", warranty_days="P1Y", weight="0.5", barcodes=["1"],
                    params=[("Цвет", "", "чёрный")])
        changes = {
            "id": "A2", "url": "https://shop.example/p/2", "price": "62891", "oldprice": "70001",
            "available": "false", "warranty_days": "P2Y", "weight": "0.6", "category_id": "1",
            "vendor": "Apple", "model": "Другая", "vendor_code": "X", "barcodes": ["2"],
            "params": [("Цвет", "", "белый")], "type_prefix": "Телефон",
        }
        original_hash = normalize(**base).content_hash()
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertNotEqual(normalize(**{**base, field: value}).content_hash(), original_hash)

    def test_hash_covers_every_field_of_the_class(self):
        base = normalize(oldprice="70000", warranty_days="P1Y", weight="0.5", barcodes=["1"],
                         params=[("Цвет", "", "чёрный")])
        other_values = {
            "external_id": "Z", "url": "https://x.example/z", "title": "другое", "price": Decimal("1.00"),
            "old_price": Decimal("9.00"), "in_stock": False, "warranty_months": 99, "weight_g": 1,
            "params": {"a": {"value": "b", "unit": ""}}, "category_slug": "laptops", "vendor": "V",
            "model": "M", "vendor_code": "C", "barcodes": ("2",),
        }
        self.assertEqual(set(other_values), {field.name for field in fields(NormalizedOffer)})
        for name, value in other_values.items():
            with self.subTest(field=name):
                self.assertNotEqual(replace(base, **{name: value}).content_hash(), base.content_hash())

    def test_insignificant_difference_in_price_notation_keeps_hash(self):
        self.assertEqual(normalize(price="1000").content_hash(), normalize(price="1000.00").content_hash())