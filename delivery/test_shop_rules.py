from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from delivery.shop_rules import FREE, load_rules, shop_delivery_options
from delivery.testing import make_city, make_offer, make_rule, make_shop


class LoadRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        cls.shop = make_shop("Первый")
        cls.other_shop = make_shop("Второй")
        cls.default_courier = make_rule(cls.shop, "400", 3, 8)
        cls.moscow_courier = make_rule(cls.shop, "200", 1, 2, city=cls.moscow)
        cls.default_pickup = make_rule(cls.shop, "100", 4, 9, method="pickup")
        make_rule(cls.other_shop, "999", 9, 9, city=cls.tomsk)

    def test_city_rule_beats_default_for_each_method_separately(self):
        rules = load_rules([self.shop.pk], self.moscow)[self.shop.pk]
        self.assertEqual(rules, {"courier": self.moscow_courier, "pickup": self.default_pickup})

    def test_guest_without_city_gets_default_rules_only(self):
        rules = load_rules([self.shop.pk, self.other_shop.pk], None)
        self.assertEqual(rules[self.shop.pk], {"courier": self.default_courier, "pickup": self.default_pickup})
        self.assertEqual(rules[self.other_shop.pk], {})

    def test_rules_of_all_shops_are_loaded_by_one_query(self):
        with self.assertNumQueries(1):
            load_rules([self.shop.pk, self.other_shop.pk], self.tomsk)

    def test_inactive_rules_are_ignored(self):
        self.default_courier.is_active = False
        self.default_courier.save()
        rules = load_rules([self.shop.pk], self.tomsk)[self.shop.pk]
        self.assertEqual(set(rules), {"pickup"})


class ShopDeliveryOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = make_shop("Магазин")
        make_rule(cls.shop, "300", 1, 2, free_from="5000")
        make_rule(cls.shop, "150", 3, 6, method="pickup", free_from="3000")

    def options(self, price):
        offer = make_offer(self.shop, price)
        return shop_delivery_options(offer, load_rules([self.shop.pk], None)[self.shop.pk])

    def test_paid_below_thresholds(self):
        courier, pickup = self.options("2999.99")
        self.assertEqual((courier.price, courier.min_days, courier.max_days, courier.source),
                         (Decimal("300"), 1, 2, "shop"))
        self.assertEqual((pickup.price, pickup.min_days, pickup.max_days), (Decimal("150"), 3, 6))

    def test_each_method_has_own_free_threshold(self):
        courier, pickup = self.options("3000")
        self.assertEqual((courier.price, pickup.price), (Decimal("300"), FREE))
        courier, pickup = self.options("5000")
        self.assertEqual((courier.price, pickup.price), (FREE, FREE))


class RuleConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = make_shop("Магазин")
        cls.city = make_city("Томск", 7)

    def assert_rejected(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_rule(self.shop, "100", **fields)

    def test_duplicate_city_method_pair_is_rejected(self):
        make_rule(self.shop, "100", city=self.city)
        self.assert_rejected(city=self.city)

    def test_min_days_above_max_days_is_rejected(self):
        self.assert_rejected(min_days=5, max_days=2)
