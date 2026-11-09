import xml.etree.ElementTree as ET
from collections import Counter
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Brand, Category, Shop
from catalog.normalize import normalize_brand
from delivery.models import City
from importer.yml_parser import iter_offers

FEEDS_DIR = settings.DEMO_FEEDS_DIR
FEED_FILES = ["citilink.yml", "dns.yml", "2droida.yml"]


def feed_offers(fname):
    """Предложения фида тем же парсером, что использует импорт."""
    with open(FEEDS_DIR / fname, "rb") as feed:
        return list(iter_offers(feed))


def feed_category_ids(fname):
    return {el.get("id") for _, el in ET.iterparse(FEEDS_DIR / fname, events=("end",)) if el.tag == "category"}


def is_valid_price(text):
    try:
        return bool(text) and Decimal(text) > 0
    except InvalidOperation:
        return False


class DemoDataLoadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)

    def test_counts(self):
        self.assertEqual(City.objects.count(), 46)
        self.assertEqual(Category.objects.count(), 5)
        self.assertEqual(Brand.objects.count(), 14)
        self.assertEqual(Shop.objects.count(), 3)

    def test_idempotent(self):
        before = (City.objects.count(), Shop.objects.count(), Brand.objects.count())
        call_command("load_demo_data", verbosity=0)
        self.assertEqual(before, (City.objects.count(), Shop.objects.count(), Brand.objects.count()))

    def test_category_tree(self):
        root = Category.objects.get(slug="electronics")
        self.assertIsNone(root.parent)
        self.assertEqual(set(root.children.values_list("slug", flat=True)),
                         {"smartphones", "laptops", "tablets", "headphones"})
        self.assertTrue(all(c.keywords for c in Category.objects.all()))

    def test_shops_have_feed_origin_and_rules(self):
        for shop in Shop.objects.all():
            self.assertTrue(shop.feed_url.startswith("http"), shop.name)
            self.assertIsNotNone(shop.origin_city, shop.name)
            self.assertTrue(shop.delivery_rules.filter(city__isnull=True).exists(), shop.name)
            self.assertEqual(shop.return_days, 7)

    def test_category_map_matches_feed(self):
        slugs = set(Category.objects.values_list("slug", flat=True))
        for shop in Shop.objects.all():
            fname = shop.feed_url.rsplit("/", 1)[-1]
            self.assertEqual(set(shop.category_map), feed_category_ids(fname), shop.name)
            self.assertTrue(set(shop.category_map.values()) <= slugs, shop.name)

    def test_feed_vendors_are_known_brands(self):
        known = set(Brand.objects.values_list("normalized_name", flat=True))
        for fname in FEED_FILES:
            for o in feed_offers(fname):
                self.assertIn(normalize_brand(o.vendor), known, (fname, o.id))

    def test_brand_normalized_name_is_produced_by_runtime_function(self):
        for brand in Brand.objects.all():
            self.assertEqual(brand.normalized_name, normalize_brand(brand.name), brand.name)

    def test_feed_url_is_built_from_setting(self):
        self.assertEqual(Shop.objects.get(name="DNS").feed_url, "http://127.0.0.1:8000/static/demo_feeds/dns.yml")
        with override_settings(DEMO_FEEDS_BASE_URL="http://localhost:9000/feeds/"):
            call_command("load_demo_data", verbosity=0)
        self.assertEqual(Shop.objects.get(name="DNS").feed_url, "http://localhost:9000/feeds/dns.yml")


class DemoFeedsTests(TestCase):
    def test_feeds_are_wellformed_and_unique_ids(self):
        for fname in FEED_FILES:
            offers = feed_offers(fname)
            self.assertEqual(len(feed_category_ids(fname)), 5, fname)
            ids = [o.id for o in offers]
            self.assertEqual(len(ids), len(set(ids)), fname)
            self.assertGreaterEqual(len(offers), 16, fname)

    def test_valid_offers_reference_existing_categories(self):
        for fname in FEED_FILES:
            categories = feed_category_ids(fname)
            for o in feed_offers(fname):
                if "-ERR-" in o.id:
                    continue
                self.assertTrue(is_valid_price(o.price), (fname, o.id))
                self.assertIn(o.category_id, categories, (fname, o.id))

    def test_intentional_errors_present(self):
        bad = Counter()
        for fname in FEED_FILES:
            categories = feed_category_ids(fname)
            for o in feed_offers(fname):
                if not is_valid_price(o.price) or o.category_id not in categories:
                    bad[fname] += 1
                    self.assertIn("-ERR-", o.id)
        self.assertEqual(bad, Counter({"dns.yml": 2, "2droida.yml": 1}))

    def test_both_yml_styles_and_missing_weight_case(self):
        cl, dns = feed_offers("citilink.yml"), feed_offers("dns.yml")
        self.assertTrue(all(o.model and not o.name for o in cl))          # vendor.model
        self.assertTrue(all(o.name for o in dns if "-ERR-" not in o.id))  # простой <name>
        self.assertTrue(any(not o.weight for o in dns))                   # нет веса -> запасной вариант

    def test_some_products_in_three_shops_and_some_not(self):
        from demo_data.build_demo_data import PRODUCTS
        counts = [len(p["shops"]) for p in PRODUCTS]
        self.assertGreaterEqual(sum(1 for c in counts if c == 3), 10)
        self.assertTrue(any(c < 3 for c in counts))  # сценарий «меньше 3 площадок»


class AdminSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)
        cls.admin = get_user_model().objects.create_superuser("root", "root@example.com", "pass-12345-x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_changelists_open(self):
        for name in ["catalog_category", "catalog_brand", "catalog_product", "catalog_shop", "catalog_offer",
                     "catalog_pricehistory", "delivery_city", "delivery_shopdeliveryrule",
                     "delivery_zonerate", "importer_importrun"]:
            r = self.client.get(reverse(f"admin:{name}_changelist"))
            self.assertEqual(r.status_code, 200, name)

    def test_search_in_admin(self):
        def found(url_name, q, attr):
            r = self.client.get(reverse(url_name), {"q": q})
            self.assertEqual(r.status_code, 200)
            return [getattr(o, attr) for o in r.context["cl"].result_list]
        self.assertEqual(found("admin:delivery_city_changelist", "Томск", "name"), ["Томск"])
        self.assertEqual(found("admin:catalog_shop_changelist", "dns", "name"), ["DNS"])
        self.assertEqual(found("admin:catalog_brand_changelist", "sony", "name"), ["Sony"])
        self.assertEqual(found("admin:catalog_category_changelist", "планшет", "slug"), ["tablets"])

    def test_shop_change_page_with_rules_inline(self):
        shop = Shop.objects.get(name="2DROIDA")
        r = self.client.get(reverse("admin:catalog_shop_change", args=[shop.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Кемерово")

    def test_city_autocomplete_endpoint(self):
        r = self.client.get(reverse("admin:autocomplete"), {
            "term": "Каз", "app_label": "catalog", "model_name": "shop", "field_name": "origin_city"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["text"] for x in r.json()["results"]], ["Казань"])