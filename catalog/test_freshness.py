from datetime import timedelta

from django.contrib.admin.sites import site
from django.test import TestCase
from django.utils import timezone

from catalog.models import DATA_STALE_AFTER, Shop


class ShopFreshnessTests(TestCase):
    def shop(self, age):
        last_import_at = None if age is None else timezone.now() - age
        return Shop.objects.create(name="Магазин", last_import_at=last_import_at)

    def test_threshold_is_48_hours(self):
        self.assertEqual(DATA_STALE_AFTER, timedelta(hours=48))

    def test_fresh_and_old_data(self):
        self.assertFalse(self.shop(timedelta(hours=47)).has_stale_data())
        self.assertTrue(self.shop(timedelta(hours=49)).has_stale_data())

    def test_exactly_at_the_threshold_is_not_stale_yet(self):
        now = timezone.now()
        shop = Shop(last_import_at=now - DATA_STALE_AFTER)
        self.assertFalse(shop.has_stale_data(now))
        self.assertTrue(shop.has_stale_data(now + timedelta(seconds=1)))

    def test_shop_never_imported_is_not_reported_as_stale(self):
        self.assertFalse(self.shop(None).has_stale_data())

    def test_admin_shows_staleness(self):
        shop_admin = site._registry[Shop]
        self.assertIn("data_is_stale", shop_admin.list_display)
        self.assertTrue(shop_admin.data_is_stale(self.shop(timedelta(days=3))))
        self.assertFalse(shop_admin.data_is_stale(self.shop(timedelta(hours=1))))
