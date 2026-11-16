from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from delivery.models import ZoneRate
from delivery.testing import make_category, make_city, make_offer, make_rate, make_shop
from delivery.tariff_cache import CACHE_TTL
from delivery.zones import zone_delivery


class ZoneDeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        cls.shop = make_shop("Зональный", origin_city=cls.moscow)
        for weight, price in (("0.5", "300"), ("1", "600"), ("2", "1200")):
            make_rate(1, 7, weight, price, 4, 9)
        make_rate(7, 1, "0.5", "310", 5, 10)
        cls.phones = make_category("smartphones")

    def test_picks_rate_for_zone_pair_and_weight_class(self):
        info = zone_delivery(make_offer(self.shop, weight_g=700), self.tomsk)
        self.assertEqual((info.price, info.min_days, info.max_days, info.source), (Decimal("600"), 4, 9, "zone"))

    def test_direction_matters(self):
        shop = make_shop("Из Томска", origin_city=self.tomsk)
        self.assertEqual(zone_delivery(make_offer(shop, weight_g=400), self.moscow).price, Decimal("310"))

    def test_weight_above_last_class(self):
        self.assertIsNone(zone_delivery(make_offer(self.shop, weight_g=5100), self.tomsk))


class ZoneRateConstraintTests(TestCase):
    def test_same_zone_pair_and_weight_class_cannot_repeat(self):
        make_rate(1, 7, "1", "600")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_rate(1, 7, "1", "700")
        make_rate(1, 7, "2", "700")
        make_rate(7, 1, "1", "700")


class ZoneCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        cls.shop = make_shop("Зональный", origin_city=cls.moscow)
        cls.rate = make_rate(1, 7, "0.5", "300", 4, 9)

    def setUp(self):
        cache.clear()

    def test_second_call_does_not_read_tariff_table(self):
        offer = make_offer(self.shop, weight_g=300)
        first = zone_delivery(offer, self.tomsk)
        with CaptureQueriesContext(connection) as queries:
            second = zone_delivery(offer, self.tomsk)
        self.assertEqual(first, second)
        self.assertFalse([q for q in queries.captured_queries if "delivery_zonerate" in q["sql"]])

    def test_cities_of_one_zone_share_cache_entry(self):
        omsk = make_city("Омск", 7)
        zone_delivery(make_offer(self.shop, weight_g=300), self.tomsk)
        with CaptureQueriesContext(connection) as queries:
            info = zone_delivery(make_offer(self.shop, weight_g=300), omsk)
        self.assertEqual(info.price, Decimal("300"))
        self.assertFalse([q for q in queries.captured_queries if "delivery_zonerate" in q["sql"]])

    def test_entry_lives_24_hours(self):
        with mock.patch("delivery.tariff_cache.cache") as fake_cache:
            fake_cache.get.return_value = None
            zone_delivery(make_offer(self.shop, weight_g=300), self.tomsk)
        key, info, ttl = fake_cache.set.call_args.args
        self.assertEqual(ttl, CACHE_TTL)
        self.assertEqual(CACHE_TTL, 86400)
        self.assertEqual(key, "delivery:zone:1:7:0.5")


class ZoneCacheInvalidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        cls.omsk = make_city("Омск", 7)
        cls.shop = make_shop("Зональный", origin_city=cls.moscow)
        cls.rate = make_rate(1, 7, "0.5", "300", 4, 9)

    def setUp(self):
        cache.clear()
        self.offer = make_offer(self.shop, weight_g=300)
        zone_delivery(self.offer, self.tomsk)
        zone_delivery(self.offer, self.omsk)

    def test_rate_edit_drops_cached_prices_of_its_zone_pair(self):
        self.rate.price = Decimal("350")
        self.rate.save()
        self.assertEqual(zone_delivery(self.offer, self.tomsk).price, Decimal("350"))
        self.assertEqual(zone_delivery(self.offer, self.omsk).price, Decimal("350"))

    def test_new_rate_of_smaller_class_is_picked_up(self):
        cache.clear()
        self.rate.delete()
        make_rate(1, 7, "2", "900")
        self.assertEqual(zone_delivery(self.offer, self.tomsk).price, Decimal("900"))
        make_rate(1, 7, "0.5", "250")
        self.assertEqual(zone_delivery(self.offer, self.tomsk).price, Decimal("250"))

    def test_city_zone_change_drops_cache_of_that_city_only(self):
        ZoneRate.objects.create(zone_from=1, zone_to=8, max_weight_kg=Decimal("0.5"), price=Decimal("500"),
                                min_days=5, max_days=9)
        self.tomsk.zone = 8
        self.tomsk.save()
        self.assertEqual(zone_delivery(self.offer, self.tomsk).price, Decimal("500"))
        with CaptureQueriesContext(connection) as queries:
            zone_delivery(self.offer, self.omsk)
        self.assertFalse([q for q in queries.captured_queries if "delivery_zonerate" in q["sql"]])

    def test_city_edit_without_zone_change_keeps_cache(self):
        self.tomsk.name = "Томск-1"
        self.tomsk.save()
        with CaptureQueriesContext(connection) as queries:
            zone_delivery(self.offer, self.tomsk)
        self.assertFalse([q for q in queries.captured_queries if "delivery_zonerate" in q["sql"]])
