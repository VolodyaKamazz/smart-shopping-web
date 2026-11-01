from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from delivery.models import City, ShopDeliveryRule, ZoneRate

WEIGHTS = [Decimal(w) for w in ("0.5", "1", "2", "3", "5")]


class ZoneRateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)

    def test_matrix_is_complete(self):
        self.assertEqual(ZoneRate.objects.count(), 10 * 10 * len(WEIGHTS))
        for zf in range(1, 11):
            for zt in range(1, 11):
                weights = list(ZoneRate.objects.filter(zone_from=zf, zone_to=zt)
                               .order_by("max_weight_kg").values_list("max_weight_kg", flat=True))
                self.assertEqual(weights, WEIGHTS, (zf, zt))

    def test_prices_follow_fas_tariff_with_vat(self):
        # ФАС № 104/26: 220/240/260/295/330 ₽ за 500 г без НДС; НДС 22%
        def price(zf, zt, w):
            return ZoneRate.objects.get(zone_from=zf, zone_to=zt, max_weight_kg=Decimal(w)).price
        self.assertEqual(price(1, 1, "0.5"), Decimal("268.40"))   # пояс 1
        self.assertEqual(price(1, 1, "1"), Decimal("536.80"))
        self.assertEqual(price(1, 1, "5"), Decimal("2684.00"))
        self.assertEqual(price(1, 2, "0.5"), Decimal("292.80"))   # Москва — Санкт-Петербург, пояс 2
        self.assertEqual(price(1, 7, "0.5"), Decimal("317.20"))   # Москва — Новосибирск, пояс 3
        self.assertEqual(price(1, 10, "0.5"), Decimal("359.90"))  # Москва — Хабаровск, пояс 4

    def test_matrix_is_symmetric_and_monotonic(self):
        for r in ZoneRate.objects.all():
            back = ZoneRate.objects.get(zone_from=r.zone_to, zone_to=r.zone_from, max_weight_kg=r.max_weight_kg)
            self.assertEqual((r.price, r.min_days, r.max_days), (back.price, back.min_days, back.max_days))
            self.assertLessEqual(r.min_days, r.max_days)
        for zf in (1, 6, 10):
            prices = list(ZoneRate.objects.filter(zone_from=zf, zone_to=1).order_by("max_weight_kg")
                          .values_list("price", flat=True))
            self.assertEqual(prices, sorted(prices))

    def test_cities_have_zones_and_regions(self):
        self.assertFalse(City.objects.filter(region="").exists())
        zones = set(City.objects.values_list("zone", flat=True))
        self.assertEqual(zones, set(range(1, 11)))
        self.assertEqual(City.objects.get(name="Москва").zone, 1)
        self.assertEqual(City.objects.get(name="Санкт-Петербург").zone, 2)
        self.assertEqual(City.objects.get(name="Томск").zone, City.objects.get(name="Новосибирск").zone)

    def test_shop_rules(self):
        self.assertEqual(ShopDeliveryRule.objects.count(), 11)
        for r in ShopDeliveryRule.objects.all():
            self.assertLessEqual(r.min_days, r.max_days)
