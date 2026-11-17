from decimal import Decimal

from django.test import TestCase

from delivery.testing import make_category, make_offer, make_shop
from delivery.weights import (DEFAULT_CATEGORY_WEIGHT_KG, category_weight_kg, offer_weight_class, offer_weight_kg,
                              weight_class)


class WeightClassTests(TestCase):
    def test_rounds_up_to_the_nearest_class(self):
        cases = {"0.1": "0.5", "0.5": "0.5", "0.501": "1", "1": "1", "1.3": "2", "2.5": "3", "3": "3", "4.99": "5",
                 "5": "5"}
        for weight, expected in cases.items():
            self.assertEqual(weight_class(Decimal(weight)), Decimal(expected), weight)


class OfferWeightTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = make_shop()
        cls.electronics = make_category("electronics")
        cls.laptops = make_category("laptops", cls.electronics)
        cls.gadgets = make_category("gadgets", cls.electronics)
        cls.cables = make_category("cables", cls.gadgets)

    def test_feed_weight_is_used_first(self):
        offer = make_offer(self.shop, category=self.laptops, weight_g=450)
        self.assertEqual(offer_weight_kg(offer), Decimal("0.45"))
        self.assertEqual(offer_weight_class(offer), Decimal("0.5"))

    def test_category_class_is_used_without_feed_weight(self):
        offer = make_offer(self.shop, category=self.laptops)
        self.assertEqual(offer_weight_kg(offer), Decimal("3"))
        self.assertEqual(offer_weight_class(offer), Decimal("3"))

    def test_default_weight_for_unknown_category_and_missing_product(self):
        self.assertEqual(offer_weight_kg(make_offer(self.shop, category=self.gadgets)), DEFAULT_CATEGORY_WEIGHT_KG)
        self.assertEqual(offer_weight_kg(make_offer(self.shop)), DEFAULT_CATEGORY_WEIGHT_KG)

    def test_category_cycle_does_not_hang(self):
        first = make_category("first")
        second = make_category("second", first)
        first.parent = second
        first.save()
        self.assertEqual(category_weight_kg(first), DEFAULT_CATEGORY_WEIGHT_KG)
