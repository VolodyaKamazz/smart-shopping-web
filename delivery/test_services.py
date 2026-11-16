from decimal import Decimal

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.models import Shop
from delivery.info import DeliveryInfo
from delivery.models import City
from delivery.services import calc_deliveries, calc_delivery_options, choose_option, unknown_delivery
from delivery.testing import make_city, make_offer, make_rate, make_rule, make_shop


class CalcDeliveryOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        make_rate(1, 7, "1", "600", 4, 9)

    def setUp(self):
        cache.clear()

    def test_shop_rules_give_variant_per_method(self):
        shop = make_shop("С правилами", origin_city=self.moscow)
        make_rule(shop, "350", 2, 4)
        make_rule(shop, "100", 5, 8, method="pickup")
        options = calc_delivery_options(make_offer(shop, weight_g=700), self.tomsk)
        self.assertEqual(options, [DeliveryInfo(Decimal("350"), 2, 4, "shop", "courier"),
                                   DeliveryInfo(Decimal("100"), 5, 8, "shop", "pickup")])

    def test_zone_table_is_used_only_when_shop_has_no_rules(self):
        shop = make_shop("Без правил", origin_city=self.moscow)
        options = calc_delivery_options(make_offer(shop, weight_g=700), self.tomsk)
        self.assertEqual(options, [DeliveryInfo(Decimal("600"), 4, 9, "zone", "pickup")])

    def test_inactive_rules_fall_through_to_zone_table(self):
        shop = make_shop("Отключён", origin_city=self.moscow)
        make_rule(shop, "350", is_active=False)
        self.assertEqual(calc_delivery_options(make_offer(shop, weight_g=700), self.tomsk)[0].source, "zone")

    def test_unknown_delivery_without_rules_and_tariff(self):
        options = calc_delivery_options(make_offer(make_shop("Без всего"), weight_g=700), self.tomsk)
        self.assertEqual(options, [unknown_delivery()])

    def test_unknown_delivery_has_no_invented_numbers(self):
        info = unknown_delivery()
        self.assertEqual((info.price, info.min_days, info.max_days, info.source, info.method),
                         (None, None, None, "unknown", ""))
        self.assertFalse(info.is_known)


class ChooseOptionTests(TestCase):
    def setUp(self):
        self.cheap_slow = DeliveryInfo(Decimal("100"), 5, 8, "shop", "pickup")
        self.fast_pricey = DeliveryInfo(Decimal("400"), 1, 2, "shop", "courier")
        self.options = [self.fast_pricey, self.cheap_slow]

    def test_price_and_balanced_choose_cheapest(self):
        self.assertIs(choose_option(self.options, "price"), self.cheap_slow)
        self.assertIs(choose_option(self.options, "balanced"), self.cheap_slow)

    def test_speed_chooses_fastest(self):
        self.assertIs(choose_option(self.options, "speed"), self.fast_pricey)

    def test_ties_are_broken_by_the_other_criterion(self):
        same_price_faster = DeliveryInfo(Decimal("100"), 1, 3, "shop", "courier")
        self.assertIs(choose_option([self.cheap_slow, same_price_faster], "price"), same_price_faster)
        same_speed_cheaper = DeliveryInfo(Decimal("50"), 1, 2, "shop", "pickup")
        self.assertIs(choose_option([self.fast_pricey, same_speed_cheaper], "speed"), same_speed_cheaper)


class CalcDeliveryPriorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tomsk = make_city("Томск", 7)
        cls.shop = make_shop("Магазин")
        make_rule(cls.shop, "400", 1, 2)
        make_rule(cls.shop, "100", 5, 8, method="pickup")


class CalcDeliveriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.moscow = make_city("Москва", 1)
        cls.tomsk = make_city("Томск", 7)
        cls.first = make_shop("Первый", origin_city=cls.moscow)
        cls.second = make_shop("Второй", origin_city=cls.moscow)
        cls.empty = make_shop("Пустой")
        make_rule(cls.first, "300", 1, 2, free_from="5000")
        make_rule(cls.second, "200", 2, 3)

    def test_each_offer_gets_conditions_of_its_shop(self):
        cheap, pricey, other, empty = (make_offer(self.first, "1000"), make_offer(self.first, "6000"),
                                       make_offer(self.second, "1000"), make_offer(self.empty, "1000"))
        result = calc_deliveries([cheap, pricey, other, empty], self.tomsk)
        self.assertEqual(result[cheap.pk].price, Decimal("300"))
        self.assertEqual(result[pricey.pk].price, Decimal("0.00"))
        self.assertEqual(result[other.pk].price, Decimal("200"))
        self.assertEqual(result[empty.pk], unknown_delivery())

    def test_rules_of_all_shops_are_loaded_once(self):
        offers = [make_offer(shop, "1000") for shop in (self.first, self.second, self.first)]
        with self.assertNumQueries(1):
            calc_deliveries(offers, self.tomsk)


class CalcDeliveryDemoDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)

    def setUp(self):
        cache.clear()

    def options(self, shop_name, price, city_name, **fields):
        shop = Shop.objects.get(name=shop_name)
        return calc_delivery_options(make_offer(shop, price, **fields), City.objects.get(name=city_name))

    def test_city_rule_with_free_threshold_and_pickup_default(self):
        self.assertEqual(self.options("Ситилинк", "4890", "Москва"), [
            DeliveryInfo(Decimal("299.00"), 1, 2, "shop", "courier"),
            DeliveryInfo(Decimal("0.00"), 1, 2, "shop", "pickup")])
        self.assertEqual(self.options("Ситилинк", "5000", "Москва")[0].price, Decimal("0.00"))

    def test_zone_table_when_shop_has_no_rules(self):
        Shop.objects.get(name="DNS").delivery_rules.all().delete()
        info = self.options("DNS", "4000", "Томск", weight_g=450)[0]
        self.assertEqual((info.price, info.source, info.method), (Decimal("317.20"), "zone", "pickup"))


class ZoneMemoTests(TestCase):
    def count_queries(self, offers_count):
        tomsk = City.objects.get(name="Томск")
        shop = Shop.objects.get(name="Зональный")
        offers = [make_offer(shop, str(1000 + i), weight_g=700) for i in range(offers_count)]
        cache.clear()
        with CaptureQueriesContext(connection) as queries:
            result = calc_deliveries(offers, tomsk)
        self.assertEqual({info.price for info in result.values()}, {Decimal("600")})
        return len(queries)

    @classmethod
    def setUpTestData(cls):
        moscow = make_city("Москва", 1)
        make_city("Томск", 7)
        make_rate(1, 7, "1", "600", 4, 9)
        make_shop("Зональный", origin_city=moscow)

    def test_query_count_does_not_depend_on_number_of_offers(self):
        self.assertEqual(self.count_queries(2), self.count_queries(40))
