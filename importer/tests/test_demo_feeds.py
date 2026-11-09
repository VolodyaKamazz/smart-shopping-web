from django.core.management import call_command
from django.db.models import Count
from django.test import TestCase

from catalog.models import Offer, Product, Shop
from demo_data.build_demo_data import PRODUCTS
from importer.services import import_shop
from importer.yml_parser import iter_offers

from .helpers import FEEDS_DIR, make_client


def feed_ids(feed_file):
    with open(FEEDS_DIR / feed_file, "rb") as feed:
        return [offer.id for offer in iter_offers(feed)]


class DemoFeedsImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", verbosity=0)

    def demo_client(self):
        routes = {shop.feed_url: (FEEDS_DIR / shop.feed_url.rsplit("/", 1)[-1]).read_bytes()
                  for shop in Shop.objects.all()}
        return make_client(routes)

    def test_every_demo_feed_imports_and_only_intentional_errors_are_skipped(self):
        with self.demo_client() as client, self.assertLogs("importer", "WARNING"):
            runs = {shop: import_shop(shop, client) for shop in Shop.objects.all()}
        for shop, run in runs.items():
            ids = feed_ids(shop.feed_url.rsplit("/", 1)[-1])
            broken = [i for i in ids if "-ERR-" in i]
            with self.subTest(shop=shop.name):
                self.assertEqual(run.status, "success")
                self.assertEqual(run.stats["errors"], len(broken))
                self.assertEqual(run.stats["created"], len(ids) - len(broken))
                self.assertEqual(Offer.objects.filter(shop=shop).count(), len(ids) - len(broken))
                self.assertTrue(all(sample.split(":")[0] in broken for sample in run.stats["error_samples"]))

    def test_second_import_changes_nothing(self):
        with self.demo_client() as client, self.assertLogs("importer", "WARNING"):
            for shop in Shop.objects.all():
                import_shop(shop, client)
            runs = [import_shop(shop, client) for shop in Shop.objects.all()]
        self.assertTrue(all(run.stats["created"] == run.stats["updated"] == 0 for run in runs))
        self.assertTrue(all(run.stats["unchanged"] > 0 for run in runs))

    def import_all(self):
        with self.demo_client() as client, self.assertLogs("importer", "WARNING"):
            for shop in Shop.objects.all():
                import_shop(shop, client)

    def test_offers_of_all_shops_are_matched_into_the_demo_products(self):
        self.import_all()
        self.assertFalse(Offer.objects.filter(product__isnull=True).exists())
        self.assertEqual(Product.objects.count(), len(PRODUCTS))
        offers_per_product = sorted(Product.objects.annotate(n=Count("offers")).values_list("n", flat=True))
        self.assertEqual(offers_per_product, sorted(len(product["shops"]) for product in PRODUCTS))

    def test_matched_products_keep_their_category_brand_and_key(self):
        self.import_all()
        for product in PRODUCTS:
            with self.subTest(model=product["model"]):
                found = Product.objects.get(model=product["model"])
                self.assertEqual(found.category.slug, product["cat"])
                self.assertEqual(found.brand.name, product["vendor"])
                self.assertEqual(found.offers.count(), len(product["shops"]))

    def test_second_import_does_not_change_products(self):
        self.import_all()
        products = list(Product.objects.order_by("pk").values())
        links = list(Offer.objects.order_by("pk").values_list("pk", "product_id"))
        self.import_all()
        self.assertEqual(list(Product.objects.order_by("pk").values()), products)
        self.assertEqual(list(Offer.objects.order_by("pk").values_list("pk", "product_id")), links)