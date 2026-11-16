from io import StringIO

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase

from catalog.models import Shop
from delivery.testing import make_offer


class CalcDeliveryCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)
        cls.citilink = Shop.objects.get(name="Ситилинк")
        cls.dns = Shop.objects.get(name="DNS")
        cls.cheap = make_offer(cls.citilink, "4000", weight_g=400)
        make_offer(cls.citilink, "9000", weight_g=400)
        cls.dns_offer = make_offer(cls.dns, "20000", weight_g=1500)

    def setUp(self):
        cache.clear()

    def run_command(self, *args):
        out = StringIO()
        call_command("calc_delivery", *args, stdout=out)
        return out.getvalue()

    def test_prints_cheapest_offer_of_each_shop_with_all_variants(self):
        output = self.run_command("Москва")
        self.assertIn("Город: Москва, зона 1", output)
        self.assertEqual(output.count("Курьер:"), 2)
        self.assertEqual(output.count("Пункт выдачи:"), 2)
        self.assertIn("Курьер: 299.00 ₽, 1–2 дн. (правило магазина)", output)
        self.assertIn("Пункт выдачи: бесплатно, 1–2 дн. (правило магазина)", output)

    def test_marks_variant_chosen_for_priority(self):
        balanced = self.run_command("Томск", "--offer", str(self.cheap.pk))
        self.assertIn("→ Пункт выдачи", balanced)
        self.assertNotIn("→ Курьер", balanced)
        speed = self.run_command("Томск", "--offer", str(self.cheap.pk), "--priority", "speed")
        self.assertIn("→ Курьер", speed)
        self.assertNotIn("→ Пункт выдачи", speed)

    def test_marks_unknown_delivery(self):
        self.citilink.delivery_rules.all().delete()
        heavy = make_offer(self.citilink, "4000", weight_g=9000)
        self.assertIn("условия уточняются", self.run_command("Томск", "--offer", str(heavy.pk)))

    def test_unknown_city(self):
        with self.assertRaisesMessage(CommandError, "Город не найден: Атлантида"):
            self.run_command("Атлантида")
