from decimal import Decimal
from itertools import count
from unittest import mock

from django.test import TestCase

from catalog import services
from catalog.models import Brand, Category, Offer, Product, Shop
from catalog.normalize import build_search_text
from catalog.services import get_offers, search_products

_external_ids = count(1)


def make_product(category, name, brand=None, **fields):
    return Product.objects.create(category=category, brand=brand, name=name, search_text=build_search_text(name),
                                  **fields)


def make_offer(product, shop, price, **fields):
    return Offer.objects.create(product=product, shop=shop, external_id=str(next(_external_ids)),
                                url="https://shop.example/p", title_raw=product.name if product else "Без товара",
                                price=price, **fields)


class CatalogFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.electronics = Category.objects.create(name="Электроника", slug="electronics")
        cls.smartphones = Category.objects.create(name="Смартфоны", slug="smartphones", parent=cls.electronics)
        cls.laptops = Category.objects.create(name="Ноутбуки", slug="laptops", parent=cls.electronics)
        cls.samsung = Brand.objects.create(name="Samsung", normalized_name="samsung")
        cls.apple = Brand.objects.create(name="Apple", normalized_name="apple")
        cls.alpha = Shop.objects.create(name="Альфа")
        cls.beta = Shop.objects.create(name="Бета")
        cls.closed = Shop.objects.create(name="Закрытый", is_active=False)


class SearchProductsTests(CatalogFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.s24 = make_product(cls.smartphones, "Смартфон Samsung Galaxy S24 8/256GB", cls.samsung)
        cls.s24_plus = make_product(cls.smartphones, "Смартфон Samsung Galaxy S24+ 12/512GB", cls.samsung)
        cls.s245 = make_product(cls.smartphones, "Смартфон Samsung Galaxy S245 Test", cls.samsung)
        cls.iphone = make_product(cls.smartphones, "Смартфон Apple iPhone 15 128GB", cls.apple)
        cls.macbook = make_product(cls.laptops, "Ноутбук Apple MacBook Air 15", cls.apple)
        for product, prices in ((cls.s24, (60000, 65000)), (cls.s24_plus, (80000,)), (cls.s245, (30000,)),
                                (cls.iphone, (70000, 72000, 75000)), (cls.macbook, (110000,))):
            for shop, price in zip((cls.alpha, cls.beta, cls.alpha), prices):
                make_offer(product, shop, price)

    def names(self, parsed):
        return [product.name for product in search_products(parsed)]

    def test_empty_query_returns_everything_with_offers(self):
        self.assertEqual(len(search_products({})), 5)

    def test_returns_products_ordered_by_number_of_offers_then_id(self):
        self.assertEqual(search_products({}), [self.iphone, self.s24, self.s24_plus, self.s245, self.macbook])

    def test_category_includes_nested_categories(self):
        phones = {self.s24, self.s24_plus, self.s245, self.iphone}
        self.assertEqual(set(search_products({"category": "smartphones"})), phones)
        self.assertEqual(search_products({"category": "laptops"}), [self.macbook])
        self.assertEqual(len(search_products({"category": "electronics"})), 5)

    def test_unknown_category_finds_nothing(self):
        self.assertEqual(search_products({"category": "no-such"}), [])

    def test_category_loop_does_not_hang(self):
        Category.objects.filter(pk=self.electronics.pk).update(parent=self.smartphones)
        self.assertEqual(len(search_products({"category": "electronics"})), 5)

    def test_brand_by_normalized_name_or_title(self):
        for value in ("apple", "Apple", " APPLE "):
            with self.subTest(value=value):
                self.assertEqual(set(search_products({"brand": value})), {self.iphone, self.macbook})

    def test_unknown_brand_finds_nothing(self):
        self.assertEqual(search_products({"brand": "nokia"}), [])

    def test_price_limits_apply_to_offer_prices(self):
        self.assertEqual(set(search_products({"price_max": 65000})), {self.s24, self.s245})
        self.assertEqual(set(search_products({"price_min": 100000})), {self.macbook})
        self.assertEqual(set(search_products({"price_min": 70000, "price_max": 72000})), {self.iphone})

    def test_limits_are_inclusive_and_accept_numbers_and_strings(self):
        for value in (60000, "60000", 60000.0, Decimal("60000.00")):
            with self.subTest(value=value):
                self.assertEqual(set(search_products({"price_max": value})), {self.s24, self.s245})

    def test_empty_limits_are_ignored(self):
        self.assertEqual(len(search_products({"price_min": None, "price_max": ""})), 5)

    def test_range_must_hold_for_one_offer(self):
        self.assertEqual(search_products({"price_min": 73000, "price_max": 74000}), [])

    def test_offers_outside_the_range_do_not_count_for_ordering(self):
        self.assertEqual(search_products({"price_min": 60000, "price_max": 71000})[:2], [self.s24, self.iphone])

    def test_keywords_must_all_be_present(self):
        self.assertEqual(self.names({"keywords": ["galaxy", "256gb"]}), [self.s24.name])
        self.assertEqual(self.names({"keywords": ["galaxy", "iphone"]}), [])

    def test_keyword_is_a_whole_word(self):
        self.assertEqual(set(search_products({"keywords": ["s24"]})), {self.s24, self.s24_plus})
        self.assertEqual(search_products({"keywords": ["s245"]}), [self.s245])

    def test_keywords_are_case_and_punctuation_insensitive(self):
        self.assertEqual(search_products({"keywords": ["GALAXY", "8/256GB"]}), [self.s24])

    def test_plus_in_keyword_narrows_to_the_plus_model(self):
        self.assertEqual(search_products({"keywords": ["S24+"]}), [self.s24_plus])
        self.assertEqual(search_products({"keywords": ["s24", "plus"]}), [self.s24_plus])

    def test_wishes_not_found_in_catalog_do_not_filter(self):
        self.assertEqual(set(search_products({"category": "smartphones", "keywords": ["хорошей", "камерой"]})),
                         {self.s24, self.s24_plus, self.s245, self.iphone})
        self.assertEqual(search_products({"keywords": ["iphone", "хорошая", "камера"]}), [self.iphone])

    def test_known_word_still_filters_when_other_filters_leave_no_match(self):
        self.assertEqual(search_products({"category": "smartphones", "keywords": ["macbook"]}), [])
        self.assertEqual(search_products({"keywords": ["iphone"], "price_max": 50000}), [])

    def test_query_where_nothing_is_recognized_finds_nothing(self):
        self.assertEqual(search_products({"keywords": ["pixel", "foldable"]}), [])
        self.assertEqual(search_products({"keywords": ["хорошая", "камера"]}), [])

    def test_wishes_alone_do_not_narrow_when_there_is_another_filter(self):
        self.assertEqual(len(search_products({"category": "smartphones", "keywords": ["хорошая", "камера"]})), 4)
        self.assertEqual(set(search_products({"price_max": 30000, "keywords": ["pixel"]})), {self.s245})
        self.assertEqual(set(search_products({"brand": "apple", "keywords": ["pixel"]})), {self.iphone, self.macbook})

    def test_zero_price_limit_counts_as_a_filter(self):
        self.assertEqual(search_products({"price_max": 0, "keywords": ["pixel"]}), [])

    def test_keywords_given_as_phrases(self):
        self.assertEqual(search_products({"keywords": ["galaxy s24"]}), [self.s24, self.s24_plus])

    def test_filters_combine(self):
        parsed = {"category": "smartphones", "brand": "samsung", "price_max": 70000, "keywords": ["galaxy"]}
        self.assertEqual(set(search_products(parsed)), {self.s24, self.s245})

    def test_products_without_available_offers_are_left_out(self):
        Offer.objects.filter(product=self.macbook).update(in_stock=False)
        Offer.objects.filter(product=self.iphone).update(is_active=False)
        self.assertEqual(set(search_products({})), {self.s24, self.s24_plus, self.s245})

    def test_offers_of_inactive_shops_do_not_count(self):
        lonely = make_product(self.smartphones, "Смартфон Samsung Только Закрытый", self.samsung)
        make_offer(lonely, self.closed, 1000)
        self.assertNotIn(lonely, search_products({}))
        self.assertNotIn(lonely, search_products({"keywords": ["закрытый"]}))

    def test_stock_matters_only_for_the_same_offer(self):
        product = make_product(self.smartphones, "Смартфон Samsung Подвох", self.samsung)
        make_offer(product, self.alpha, 1000, in_stock=False)
        make_offer(product, self.beta, 90000)
        self.assertNotIn(product, search_products({"price_max": 5000}))

    def test_product_without_offers_is_left_out(self):
        make_product(self.smartphones, "Смартфон Samsung Без Предложений", self.samsung)
        self.assertEqual(len(search_products({})), 5)

    def test_result_is_limited(self):
        with mock.patch.object(services, "MAX_PRODUCTS", 2):
            self.assertEqual(search_products({}), [self.iphone, self.s24])

    def test_number_of_queries_is_constant(self):
        parsed = {"category": "smartphones", "brand": "samsung", "price_max": 70000, "keywords": ["galaxy", "s24"]}
        with self.assertNumQueries(4):
            search_products(parsed)


class GetOffersTests(CatalogFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.phone = make_product(cls.smartphones, "Смартфон Samsung Galaxy S24", cls.samsung)
        cls.other = make_product(cls.smartphones, "Смартфон Apple iPhone 15", cls.apple)
        cls.expensive = make_offer(cls.phone, cls.alpha, 65000)
        cls.cheap = make_offer(cls.phone, cls.beta, 60000)
        cls.other_offer = make_offer(cls.other, cls.alpha, 70000)

    def test_returns_offers_of_requested_products_cheapest_first(self):
        self.assertEqual(get_offers([self.phone.pk]), [self.cheap, self.expensive])
        self.assertEqual(get_offers([self.other.pk, self.phone.pk]), [self.cheap, self.expensive, self.other_offer])

    def test_unavailable_offers_are_left_out(self):
        make_offer(self.phone, self.alpha, 50000, in_stock=False)
        make_offer(self.phone, self.alpha, 51000, is_active=False)
        make_offer(self.phone, self.closed, 52000)
        self.assertEqual(get_offers([self.phone.pk]), [self.cheap, self.expensive])

    def test_equal_prices_keep_a_stable_order(self):
        twin = make_offer(self.phone, self.alpha, 60000)
        self.assertEqual(get_offers([self.phone.pk])[:2], [self.cheap, twin])

    def test_offers_without_product_are_never_returned(self):
        make_offer(None, self.alpha, 100)
        self.assertEqual(len(get_offers([self.phone.pk, self.other.pk])), 3)

    def test_empty_or_unknown_ids(self):
        with self.assertNumQueries(0):
            self.assertEqual(get_offers([]), [])
        self.assertEqual(get_offers([999999]), [])

    def test_shop_and_product_are_loaded_with_the_offers(self):
        with self.assertNumQueries(1):
            offers = get_offers([self.phone.pk, self.other.pk])
            self.assertEqual([(offer.shop.name, offer.product.name) for offer in offers],
                             [("Бета", "Смартфон Samsung Galaxy S24"), ("Альфа", "Смартфон Samsung Galaxy S24"),
                              ("Альфа", "Смартфон Apple iPhone 15")])

    def test_search_result_feeds_get_offers(self):
        products = search_products({"keywords": ["galaxy"]})
        self.assertEqual(get_offers([product.pk for product in products]), [self.cheap, self.expensive])