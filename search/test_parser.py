from django.test import SimpleTestCase

from .parser import parse_query, stem

CATEGORIES = [
    {"slug": "electronics", "name": "Электроника", "keywords": "электроника, техника, гаджет"},
    {"slug": "smartphones", "name": "Смартфоны", "keywords": "смартфон, смартфоны, телефон, телефоны, мобильный"},
    {"slug": "laptops", "name": "Ноутбуки", "keywords": "ноутбук, ноутбуки, ультрабук, макбук"},
    {"slug": "tablets", "name": "Планшеты", "keywords": "планшет, планшеты, планшетный компьютер, айпад"},
    {"slug": "headphones", "name": "Наушники", "keywords": "наушники, наушник, гарнитура, беспроводные наушники, tws"},
]
BRANDS = [
    {"name": "Apple", "normalized_name": "apple"},
    {"name": "Samsung", "normalized_name": "samsung"},
    {"name": "Xiaomi", "normalized_name": "xiaomi"},
    {"name": "ASUS", "normalized_name": "asus"},
    {"name": "JBL", "normalized_name": "jbl"},
]


def parse(text):
    return parse_query(text, CATEGORIES, BRANDS)


class PriceTests(SimpleTestCase):
    def test_max_price_variants(self):
        cases = {
            "смартфон до 50000": 50000,
            "смартфон до 50 000": 50000,
            "смартфон до 50 000 рублей": 50000,
            "смартфон до 50000₽": 50000,
            "смартфон до 50к": 50000,
            "смартфон до 50 тыс": 50000,
            "смартфон до 50 тысяч рублей": 50000,
            "смартфон не дороже 30000": 30000,
            "смартфон дешевле 30000": 30000,
            "смартфон за 90к": 90000,
            "смартфон максимум 25 000 руб.": 25000,
            "смартфон в пределах 40000": 40000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = parse(text)
                self.assertEqual(result["price_max"], expected)
                self.assertIsNone(result["price_min"])

    def test_min_price(self):
        for text in ("ноутбук от 40000", "ноутбук дороже 40000", "ноутбук не дешевле 40 000 руб"):
            with self.subTest(text=text):
                result = parse(text)
                self.assertEqual(result["price_min"], 40000)
                self.assertIsNone(result["price_max"])

    def test_range(self):
        result = parse("ноутбук от 40000 до 80000")
        self.assertEqual((result["price_min"], result["price_max"]), (40000, 80000))

    def test_range_with_shared_unit(self):
        result = parse("планшет от 20 до 30 тыс")
        self.assertEqual((result["price_min"], result["price_max"]), (20000, 30000))

    def test_swapped_range_is_fixed(self):
        result = parse("ноутбук от 80000 до 40000")
        self.assertEqual((result["price_min"], result["price_max"]), (40000, 80000))

    def test_no_price(self):
        result = parse("смартфон samsung")
        self.assertIsNone(result["price_min"])
        self.assertIsNone(result["price_max"])

    def test_numbers_without_marker_are_not_prices(self):
        result = parse("смартфон 128 гб")
        self.assertIsNone(result["price_max"])
        self.assertIn("128", result["keywords"])

    def test_price_words_are_not_keywords(self):
        result = parse("смартфон до 50000 рублей")
        self.assertEqual(result["keywords"], [])


class CategoryTests(SimpleTestCase):
    def test_category_by_name_and_synonyms(self):
        cases = {
            "смартфон": "smartphones",
            "смартфоны": "smartphones",
            "телефон": "smartphones",
            "ноутбуков": "laptops",
            "ультрабук": "laptops",
            "наушники": "headphones",
            "планшет": "tablets",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse(text)["category"], expected)

    def test_longer_term_wins(self):
        self.assertEqual(parse("беспроводные наушники")["category"], "headphones")

    def test_no_category(self):
        self.assertIsNone(parse("чайник")["category"])

    def test_category_word_is_not_keyword(self):
        self.assertEqual(parse("смартфон")["keywords"], [])

    def test_stem(self):
        self.assertEqual(stem("смартфоны"), stem("смартфонов"))
        self.assertEqual(stem("Ноутбуки"), stem("ноутбук"))


class BrandTests(SimpleTestCase):
    def test_latin_brand(self):
        self.assertEqual(parse("смартфон Samsung")["brand"], "samsung")

    def test_cyrillic_brand(self):
        self.assertEqual(parse("наушники самсунг")["brand"], "samsung")
        self.assertEqual(parse("ноутбук асус")["brand"], "asus")

    def test_brand_by_model_name(self):
        result = parse("айфон 15 pro")
        self.assertEqual(result["brand"], "apple")
        self.assertEqual(result["keywords"], ["iphone", "15", "pro"])

    def test_unknown_brand_stays_keyword(self):
        result = parse("смартфон nothing")
        self.assertIsNone(result["brand"])
        self.assertEqual(result["keywords"], ["nothing"])

    def test_brand_word_is_not_keyword(self):
        self.assertEqual(parse("смартфон samsung")["keywords"], [])


class FullQueryTests(SimpleTestCase):
    def test_example_query(self):
        self.assertEqual(
            parse("Хочу купить смартфон Samsung до 50 000 рублей с хорошей камерой"),
            {
                "category": "smartphones",
                "brand": "samsung",
                "price_min": None,
                "price_max": 50000,
                "keywords": ["хорошей", "камерой"],
            },
        )

    def test_empty_query(self):
        self.assertEqual(
            parse("   "),
            {"category": None, "brand": None, "price_min": None, "price_max": None, "keywords": []},
        )

    def test_none_query(self):
        self.assertEqual(parse(None)["keywords"], [])

    def test_empty_dictionaries(self):
        result = parse_query("смартфон samsung до 10000", [], [])
        self.assertIsNone(result["category"])
        self.assertIsNone(result["brand"])
        self.assertEqual(result["price_max"], 10000)
        self.assertEqual(result["keywords"], ["смартфон", "samsung"])

    def test_case_insensitive(self):
        result = parse("СМАРТФОН SAMSUNG ДО 50000")
        self.assertEqual((result["category"], result["brand"], result["price_max"]), ("smartphones", "samsung", 50000))
