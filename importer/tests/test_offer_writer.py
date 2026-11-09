from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from catalog.models import Brand, Category, Offer, PriceHistory, Product, Shop
from importer import offer_writer
from importer.offer_writer import write_offers

from .helpers import normalize


class WriteOffersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = Shop.objects.create(name="Магазин", feed_url="http://shop.example/feed.yml")
        cls.other_shop = Shop.objects.create(name="Другой", feed_url="http://other.example/feed.yml")

    def write(self, *offers, shop=None, seen_at=None, **kwargs):
        return write_offers(shop or self.shop, list(offers), seen_at or timezone.now(), **kwargs)

    def test_new_offers_are_created_with_all_fields(self):
        seen_at = timezone.now()
        stats = self.write(normalize(oldprice="70000", warranty_days="P1Y", weight="0.45",
                                     params=[("Цвет", "", "чёрный")]), seen_at=seen_at)
        self.assertEqual((stats.created, stats.updated, stats.unchanged), (1, 0, 0))
        offer = Offer.objects.get()
        self.assertEqual(offer.shop, self.shop)
        self.assertEqual(offer.external_id, "A1")
        self.assertEqual(offer.title_raw, "Смартфон Samsung Galaxy S24 8/256GB")
        self.assertEqual((offer.price, offer.old_price), (Decimal("62890.00"), Decimal("70000.00")))
        self.assertTrue(offer.in_stock)
        self.assertEqual((offer.warranty_months, offer.weight_g), (12, 450))
        self.assertEqual(offer.params, {"Цвет": {"value": "чёрный", "unit": ""}})
        self.assertEqual(len(offer.content_hash), 64)
        self.assertTrue(offer.is_active)
        self.assertIsNone(offer.product)
        self.assertEqual(offer.last_seen_at, seen_at)

    def test_new_offer_gets_first_history_row(self):
        self.write(normalize(available="false"))
        row = PriceHistory.objects.get()
        self.assertEqual((row.offer, row.price, row.in_stock), (Offer.objects.get(), Decimal("62890.00"), False))

    def test_unchanged_offer_is_not_rewritten_but_marked_as_seen(self):
        first_seen = timezone.now() - timedelta(hours=6)
        self.write(normalize(), seen_at=first_seen)
        updated_at = Offer.objects.get().updated_at

        second_seen = timezone.now()
        stats = self.write(normalize(), seen_at=second_seen)

        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 0, 1))
        offer = Offer.objects.get()
        self.assertEqual(offer.updated_at, updated_at)
        self.assertEqual(offer.last_seen_at, second_seen)
        self.assertEqual(PriceHistory.objects.count(), 1)

    def test_price_change_updates_offer_and_adds_history(self):
        self.write(normalize(price="62890"))
        updated_at = Offer.objects.get().updated_at

        stats = self.write(normalize(price="59990", oldprice="62890"))

        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 1, 0))
        offer = Offer.objects.get()
        self.assertEqual((offer.price, offer.old_price), (Decimal("59990.00"), Decimal("62890.00")))
        self.assertGreater(offer.updated_at, updated_at)
        self.assertEqual(list(PriceHistory.objects.order_by("pk").values_list("price", flat=True)),
                         [Decimal("62890.00"), Decimal("59990.00")])

    def test_stock_change_adds_history(self):
        self.write(normalize(available="true"))
        self.write(normalize(available="false"))
        self.assertFalse(Offer.objects.get().in_stock)
        self.assertEqual(list(PriceHistory.objects.order_by("pk").values_list("in_stock", flat=True)), [True, False])

    def test_other_changes_update_offer_without_history(self):
        self.write(normalize())
        stats = self.write(normalize(url="https://shop.example/p/new", warranty_days="P2Y",
                                     params=[("Цвет", "", "белый")]))
        self.assertEqual(stats.updated, 1)
        offer = Offer.objects.get()
        self.assertEqual(offer.url, "https://shop.example/p/new")
        self.assertEqual(offer.warranty_months, 24)
        self.assertEqual(offer.params, {"Цвет": {"value": "белый", "unit": ""}})
        self.assertEqual(PriceHistory.objects.count(), 1)

    def test_mixed_batch(self):
        self.write(normalize(id="1", price="100"), normalize(id="2", price="200"), normalize(id="3", price="300"))
        stats = self.write(normalize(id="1", price="100"), normalize(id="2", price="250"),
                           normalize(id="3", price="300"), normalize(id="4", price="400"))
        self.assertEqual((stats.created, stats.updated, stats.unchanged), (1, 1, 2))
        self.assertEqual(Offer.objects.get(external_id="2").price, Decimal("250.00"))
        self.assertEqual(PriceHistory.objects.count(), 5)

    def test_offers_of_different_shops_do_not_clash(self):
        self.write(normalize(id="same"))
        stats = self.write(normalize(id="same"), shop=self.other_shop)
        self.assertEqual(stats.created, 1)
        self.assertEqual(Offer.objects.count(), 2)

    def test_offers_missing_from_feed_are_left_alone(self):
        self.write(normalize(id="1"), normalize(id="2"))
        self.write(normalize(id="1"))
        self.assertEqual(Offer.objects.filter(is_active=True).count(), 2)

    def test_import_does_not_touch_is_active(self):
        self.write(normalize())
        Offer.objects.update(is_active=False)
        self.write(normalize(price="1"))
        self.assertFalse(Offer.objects.get().is_active)

    def test_works_across_several_chunks(self):
        offers = [normalize(id=str(i), price=str(100 + i)) for i in range(25)]
        stats = self.write(*offers, chunk_size=10)
        self.assertEqual(stats.created, 25)
        offers[3] = normalize(id="3", price="1")
        stats = self.write(*offers, chunk_size=10)
        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 1, 24))
        self.assertEqual(PriceHistory.objects.count(), 26)

    def test_failure_in_later_chunk_rolls_back_the_whole_import(self):
        self.write(normalize(id="old", price="100"))
        before = (list(Offer.objects.values()), PriceHistory.objects.count())
        offers = [normalize(id="old", price="150")] + [normalize(id=str(i)) for i in range(7)]
        real_write_chunk = offer_writer._write_chunk
        calls = []

        def fail_on_third_chunk(shop, chunk, seen_at, stats):
            calls.append(chunk)
            if len(calls) == 3:
                raise RuntimeError("сбой записи")
            return real_write_chunk(shop, chunk, seen_at, stats)

        with mock.patch("importer.offer_writer._write_chunk", fail_on_third_chunk), \
                self.assertRaisesMessage(RuntimeError, "сбой записи"):
            self.write(*offers, chunk_size=3)

        self.assertEqual(len(calls), 3)
        self.assertEqual((list(Offer.objects.values()), PriceHistory.objects.count()), before)

    def test_update_keeps_pk_product_and_is_active(self):
        self.write(normalize(price="100"))
        offer = Offer.objects.get()
        offer.is_active = False
        offer.save()
        old_pk = offer.pk

        self.write(normalize(price="90"))

        offer = Offer.objects.get()
        self.assertEqual(offer.pk, old_pk)
        self.assertEqual(str(offer.price), "90.00")
        self.assertFalse(offer.is_active)
        self.assertEqual(PriceHistory.objects.filter(offer_id=old_pk).count(), 2)

    def test_missing_pks_are_filled_from_db(self):
        self.write(normalize(id="1"), normalize(id="2"))
        unsaved = [Offer(shop=self.shop, external_id="1"), Offer(shop=self.shop, external_id="2")]
        offer_writer._fill_missing_pks(self.shop, unsaved)
        self.assertEqual({o.external_id: o.pk for o in unsaved},
                         dict(Offer.objects.values_list("external_id", "pk")))

    def test_accepts_generator(self):
        stats = write_offers(self.shop, (normalize(id=str(i)) for i in range(3)), timezone.now())
        self.assertEqual(stats.created, 3)

    def test_empty_input(self):
        stats = self.write()
        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 0, 0))


class WriteOffersMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = Shop.objects.create(name="Магазин", feed_url="http://shop.example/feed.yml")
        cls.other_shop = Shop.objects.create(name="Другой", feed_url="http://other.example/feed.yml")
        cls.electronics = Category.objects.create(name="Электроника", slug="electronics")
        cls.smartphones = Category.objects.create(name="Смартфоны", slug="smartphones", parent=cls.electronics)

    def write(self, *offers, shop=None, **kwargs):
        return write_offers(shop or self.shop, list(offers), timezone.now(), **kwargs)

    def test_new_offers_get_a_product_and_the_same_model_shares_it(self):
        self.write(normalize(id="1"), normalize(id="2", price="100"), normalize(id="3", model="Galaxy S24+ 12/512GB"))
        first, second, third = (Offer.objects.get(external_id=i) for i in "123")
        self.assertEqual(first.product, second.product)
        self.assertNotEqual(first.product, third.product)
        self.assertEqual(Product.objects.count(), 2)

    def test_same_model_in_another_shop_is_the_same_product(self):
        self.write(normalize())
        self.write(normalize(vendor="SAMSUNG", model="galaxy s24 8/256gb"), shop=self.other_shop)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual({offer.product_id for offer in Offer.objects.all()}, {Product.objects.get().pk})

    def test_barcodes_from_the_feed_are_used(self):
        self.write(normalize(barcodes=["4006381333931"]))
        self.write(normalize(model="Другое название", barcodes=["4006381333931"]), shop=self.other_shop)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Product.objects.get().gtin, "4006381333931")

    def test_second_import_does_not_create_products_or_touch_links(self):
        self.write(normalize(id="1"), normalize(id="2", model="Другая"))
        links = dict(Offer.objects.values_list("external_id", "product_id"))
        products = list(Product.objects.values())
        self.write(normalize(id="1"), normalize(id="2", model="Другая"))
        self.assertEqual(dict(Offer.objects.values_list("external_id", "product_id")), links)
        self.assertEqual(list(Product.objects.values()), products)

    def write_without_matching(self, *offers):
        with mock.patch("importer.offer_writer.match_offers", side_effect=lambda items: [None] * len(items)):
            return self.write(*offers)

    def test_unchanged_offer_without_product_is_matched(self):
        self.write_without_matching(normalize(id="1"), normalize(id="2"))
        self.assertEqual(Offer.objects.filter(product__isnull=True).count(), 2)
        updated_at = Offer.objects.get(external_id="1").updated_at

        stats = self.write(normalize(id="1"), normalize(id="2"))

        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 0, 2))
        self.assertEqual(Offer.objects.filter(product__isnull=True).count(), 0)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Offer.objects.get(external_id="1").updated_at, updated_at)

    def test_changed_offer_without_product_is_matched(self):
        self.write_without_matching(normalize(price="100"))
        stats = self.write(normalize(price="500"))
        self.assertEqual((stats.created, stats.updated, stats.unchanged), (0, 1, 0))
        offer = Offer.objects.get()
        self.assertEqual(offer.price, 500)
        self.assertEqual(offer.product, Product.objects.get())

    def test_offer_that_lost_its_product_is_matched_again(self):
        self.write(normalize())
        Product.objects.all().delete()
        self.assertIsNone(Offer.objects.get().product)
        self.write(normalize())
        self.assertEqual(Offer.objects.get().product, Product.objects.get())

    def test_existing_product_is_never_replaced(self):
        """Правка product в админке переживает любые импорты, даже если данные предложения изменились."""
        self.write(normalize(price="100"))
        chosen = Product.objects.create(category=self.smartphones, name="Выбран вручную")
        Offer.objects.update(product=chosen)
        self.write(normalize(price="90", model="Совсем другая модель"))
        self.write(normalize(price="90", model="Совсем другая модель"))
        self.assertEqual(Offer.objects.get().product, chosen)
        self.assertEqual(Product.objects.count(), 2)

    def test_offer_in_unknown_category_stays_without_product_and_does_not_break_import(self):
        lost = replace(normalize(id="2"), category_slug="no-such-category")
        with self.assertLogs("catalog.matching", "WARNING"):
            stats = self.write(normalize(id="1"), lost)
        self.assertEqual(stats.created, 2)
        self.assertIsNotNone(Offer.objects.get(external_id="1").product)
        self.assertIsNone(Offer.objects.get(external_id="2").product)

    def test_matching_works_across_chunks(self):
        offers = [normalize(id=str(i), model=f"Модель {i % 4}") for i in range(10)]
        self.write(*offers, chunk_size=3)
        self.assertEqual(Product.objects.count(), 4)
        self.assertEqual(Offer.objects.filter(product__isnull=True).count(), 0)

    def test_failure_rolls_back_products_and_brands_too(self):
        offers = [normalize(id=str(i), vendor=f"Бренд{i}", model=f"М{i}") for i in range(6)]
        real_write_chunk = offer_writer._write_chunk
        calls = []

        def fail_on_third_chunk(shop, chunk, seen_at, stats):
            calls.append(chunk)
            if len(calls) == 3:
                raise RuntimeError("сбой записи")
            return real_write_chunk(shop, chunk, seen_at, stats)

        with mock.patch("importer.offer_writer._write_chunk", fail_on_third_chunk), \
                self.assertRaisesMessage(RuntimeError, "сбой записи"):
            self.write(*offers, chunk_size=2)

        self.assertEqual(len(calls), 3)
        self.assertEqual((Offer.objects.count(), Product.objects.count(), Brand.objects.count()), (0, 0, 0))