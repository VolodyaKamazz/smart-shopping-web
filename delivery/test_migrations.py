from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RuleMigrationTests(TransactionTestCase):
    before = [("delivery", "0001_initial"), ("catalog", "0003_offer_url_2048")]
    after = [("delivery", "0002_delivery_method_and_rule_constraints")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_duplicates_are_removed_and_reversed_days_are_swapped(self):
        old_apps = self.migrate(self.before)
        shop = old_apps.get_model("catalog", "Shop").objects.create(name="Магазин")
        city = old_apps.get_model("delivery", "City").objects.create(name="Томск", region="Томская область", zone=7)
        rule_model = old_apps.get_model("delivery", "ShopDeliveryRule")
        first = rule_model.objects.create(shop=shop, city=city, cost=100, min_days=1, max_days=2)
        rule_model.objects.create(shop=shop, city=city, cost=200, min_days=1, max_days=2)
        rule_model.objects.create(shop=shop, city=None, cost=300, min_days=1, max_days=2)
        rule_model.objects.create(shop=shop, city=None, cost=400, min_days=1, max_days=2)
        reversed_city = old_apps.get_model("delivery", "City").objects.create(name="Омск", region="Омская область", zone=7)
        swapped = rule_model.objects.create(shop=shop, city=reversed_city, cost=500, min_days=9, max_days=3)

        new_apps = self.migrate(self.after)
        rules = new_apps.get_model("delivery", "ShopDeliveryRule").objects
        self.assertEqual(rules.count(), 3)
        self.assertEqual(rules.get(city_id=city.pk).pk, first.pk)
        self.assertEqual(rules.get(city__isnull=True).cost, 300)
        fixed = rules.get(pk=swapped.pk)
        self.assertEqual((fixed.min_days, fixed.max_days, fixed.method, fixed.is_active), (3, 9, "courier", True))


class ZoneRateMigrationTests(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_duplicate_rates_are_removed_keeping_the_first(self):
        old_apps = self.migrate([("delivery", "0002_delivery_method_and_rule_constraints")])
        rate_model = old_apps.get_model("delivery", "ZoneRate")
        first = rate_model.objects.create(zone_from=1, zone_to=7, max_weight_kg="1", price=100, min_days=2, max_days=5)
        rate_model.objects.create(zone_from=1, zone_to=7, max_weight_kg="1", price=999, min_days=2, max_days=5)
        rate_model.objects.create(zone_from=1, zone_to=7, max_weight_kg="2", price=200, min_days=2, max_days=5)

        new_apps = self.migrate([("delivery", "0003_zone_rate_unique_class")])
        rates = new_apps.get_model("delivery", "ZoneRate").objects
        self.assertEqual(rates.count(), 2)
        self.assertEqual(rates.get(max_weight_kg="1").pk, first.pk)
