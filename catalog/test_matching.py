from dataclasses import replace
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.matching import MAX_MODEL_LEN, MAX_MPN_LEN, match_offers
from catalog.models import Brand, Category, Product
from catalog.normalize import build_match_key
from importer.tests.helpers import normalize

GTIN_A = "4006381333931"
GTIN_B = "5901234123457"


def offer(**fields):
    return normalize(**fields)


class MatchOffersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.electronics = Category.objects.create(name="Электроника", slug="electronics")
        cls.smartphones = Category.objects.create(name="Смартфоны", slug="smartphones", parent=cls.electronics)

    def match(self, *offers):
        return match_offers(offers)

    def test_new_offer_creates_a_product_from_it(self):
        item = offer(barcodes=[GTIN_A], params=[("Диагональ экрана", "дюйм", "6.2")])
        [product_id] = self.match(item)
        product = Product.objects.get(pk=product_id)
        self.assertEqual(product.category, self.smartphones)
        self.assertEqual((product.brand.name, product.brand.normalized_name), ("Samsung", "samsung"))
        self.assertEqual(product.name, item.title)
        self.assertEqual((product.model, product.mpn, product.gtin), ("Galaxy S24 8/256GB", "SM-S921B", GTIN_A))
        self.assertEqual(product.match_key, "samsung|galaxy s24 8 256gb")
        self.assertEqual(product.attributes, item.params)
        for word in ("смартфон", "samsung", "galaxy", "s24", "256gb", "sm", "s921b"):
            self.assertIn(f" {word} ", product.search_text)

    def test_same_model_from_another_shop_is_the_same_product(self):
        first = self.match(offer(), offer(model="Galaxy S24 8/256GB", vendor_code="X"))
        second = self.match(offer(vendor="SAMSUNG", model="galaxy s24 8-256gb"))
        self.assertEqual(set(first + second), {first[0]})
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Brand.objects.count(), 1)

    def test_gtin_wins_over_match_key(self):
        [by_key] = self.match(offer(model="Galaxy S24 8/256GB"))
        [by_gtin] = self.match(offer(model="Galaxy S24+ 12/512GB", barcodes=[GTIN_A]))
        self.assertNotEqual(by_key, by_gtin)
        self.assertEqual(self.match(offer(model="Galaxy S24 8/256GB", barcodes=[GTIN_A])), [by_gtin])

    def test_gtin_matches_even_when_names_differ(self):
        [first] = self.match(offer(barcodes=[GTIN_A]))
        [second] = self.match(offer(vendor="Самсунг", model="Совсем другое название", barcodes=["1", GTIN_A]))
        self.assertEqual(first, second)
        self.assertEqual(Product.objects.count(), 1)

    def test_invalid_check_digit_is_not_a_gtin(self):
        [first] = self.match(offer(model="Модель 1", barcodes=["4006381333932"]))
        [second] = self.match(offer(model="Модель 2", barcodes=["4006381333932"]))
        self.assertNotEqual(first, second)
        self.assertEqual(Product.objects.get(pk=first).gtin, "")

    def test_different_models_stay_apart(self):
        ids = self.match(*(offer(model=m) for m in
                           ("Galaxy S24 8/256GB", "Galaxy S24+ 8/256GB", "Galaxy S24 8/512GB", "Galaxy S24 Ultra")))
        self.assertEqual(len(set(ids)), 4)

    def test_plus_and_plus_word_are_the_same_model(self):
        ids = self.match(offer(model="Galaxy S24+ 12/512GB"), offer(model="Galaxy S24 Plus 12/512GB"))
        self.assertEqual(len(set(ids)), 1)

    def test_same_key_in_another_category_is_not_merged(self):
        [phone] = self.match(offer(model="X1"))
        [laptop] = self.match(offer(model="X1", category_id="1"))
        self.assertNotEqual(phone, laptop)

    def test_different_gtins_with_the_same_key_are_not_merged(self):
        [first] = self.match(offer(barcodes=[GTIN_A]))
        [second] = self.match(offer(barcodes=[GTIN_B]))
        self.assertNotEqual(first, second)
        self.assertEqual(Product.objects.get(pk=second).gtin, GTIN_B)

    def test_offer_without_gtin_joins_product_with_gtin_by_key(self):
        [first] = self.match(offer(barcodes=[GTIN_A]))
        self.assertEqual(self.match(offer()), [first])

    def test_several_candidates_the_earliest_wins(self):
        self.match(offer(barcodes=[GTIN_A]))
        self.match(offer(barcodes=[GTIN_B]))
        earliest = Product.objects.order_by("pk").first().pk
        self.assertEqual(self.match(offer()), [earliest])

    def test_product_without_gtin_gets_the_first_gtin_from_a_matching_offer(self):
        [product_id] = self.match(offer())
        self.assertEqual(self.match(offer(barcodes=[GTIN_A])), [product_id])
        self.assertEqual(Product.objects.get(pk=product_id).gtin, GTIN_A)
        self.assertNotEqual(self.match(offer(barcodes=[GTIN_B])), [product_id])
        self.assertEqual(self.match(offer(model="Иначе", barcodes=[GTIN_A])), [product_id])

    def test_gtin_is_filled_for_a_product_created_in_the_same_batch(self):
        first, second, third = self.match(offer(), offer(barcodes=[GTIN_A]), offer(barcodes=[GTIN_B]))
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(Product.objects.get(pk=first).gtin, GTIN_A)

    def test_duplicates_in_one_batch_become_one_product(self):
        ids = self.match(offer(), offer(vendor_code="Y"), offer(model="Другая"))
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])
        self.assertEqual(Product.objects.count(), 2)

    def test_existing_brand_is_reused(self):
        brand = Brand.objects.create(name="Samsung Electronics", normalized_name="samsung")
        [product_id] = self.match(offer())
        self.assertEqual(Product.objects.get(pk=product_id).brand, brand)
        self.assertEqual(Brand.objects.count(), 1)

    def test_offers_without_usable_key_never_merge(self):
        ids = self.match(offer(vendor="---"), offer(vendor="---"))
        self.assertEqual(len(set(ids)), 2)
        product = Product.objects.get(pk=ids[0])
        self.assertEqual((product.match_key, product.brand), ("", None))

    def test_unknown_category_gives_none_and_does_not_block_the_others(self):
        lost = replace(offer(model="Потерянная"), category_slug="no-such-category")
        with self.assertLogs("catalog.matching", "WARNING") as logs:
            ids = self.match(offer(), lost, replace(lost, model="Ещё одна"))
        self.assertIsNotNone(ids[0])
        self.assertEqual(ids[1:], [None, None])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("'no-such-category'", logs.output[0])
        self.assertIn("2 предложений", logs.output[0])
        self.assertEqual(Product.objects.count(), 1)

    def test_offer_is_matched_once_its_category_appears(self):
        lost = replace(offer(), category_slug="laptops")
        with self.assertLogs("catalog.matching", "WARNING"):
            self.assertEqual(self.match(lost), [None])
        Category.objects.create(name="Ноутбуки", slug="laptops")
        self.assertIsNotNone(self.match(lost)[0])

    def test_empty_input(self):
        with self.assertNumQueries(0):
            self.assertEqual(match_offers([]), [])

    def test_overlong_fields_are_cut_to_the_product_limits(self):
        item = offer(model="М" * 300, vendor_code="a" * 150)
        [product_id] = self.match(item)
        product = Product.objects.get(pk=product_id)
        self.assertEqual((len(product.model), len(product.mpn)), (MAX_MODEL_LEN, MAX_MPN_LEN))
        self.assertEqual(product.match_key, "")

    def test_works_when_the_database_does_not_return_ids_after_insert(self):
        feature = mock.patch.object(type(connection.features), "can_return_rows_from_bulk_insert",
                                    new_callable=mock.PropertyMock, return_value=False)
        with feature:
            ids = self.match(offer(), offer(model="Другая"))
        self.assertEqual(sorted(ids), sorted(Product.objects.values_list("pk", flat=True)))

    def test_number_of_queries_does_not_depend_on_batch_size(self):
        def count(size, prefix, gtin):
            items = [offer(model=f"{prefix} {i}", barcodes=[gtin] if i == 0 else []) for i in range(size)]
            with CaptureQueriesContext(connection) as queries:
                self.match(*items)
            return len(queries)
        self.match(offer(model="Прогрев"))
        self.assertEqual(count(3, "Малая", GTIN_A), count(60, "Большая", GTIN_B))

    def test_logs_how_offers_were_matched(self):
        self.match(offer(barcodes=[GTIN_A]))
        with self.assertLogs("catalog.matching", "DEBUG") as logs:
            self.match(offer(barcodes=[GTIN_A]), offer(), offer(model="Новая"))
        self.assertIn("по gtin 1, по match_key 1, новых товаров 1, без категории 0", logs.output[0])

    def test_keys_use_the_same_normalization_as_build_match_key(self):
        [product_id] = self.match(offer(vendor="Hewlett-Packard", model="Pavilion 15+"))
        expected = build_match_key("Hewlett-Packard", "Pavilion 15+")
        self.assertEqual(Product.objects.get(pk=product_id).match_key, expected)