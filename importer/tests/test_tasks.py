from unittest import mock

from django.test import TestCase

from catalog.models import Offer, Shop
from importer.models import ImportRun
from importer.tasks import import_feeds

from .helpers import make_client, make_shop, many_offers_feed


class ImportFeedsTaskTests(TestCase):
    def setUp(self):
        self.alpha, self.beta = make_shop("Альфа"), make_shop("Бета")
        self.routes = {self.alpha.feed_url: many_offers_feed(2), self.beta.feed_url: many_offers_feed(3)}

    def run_task(self, *args, routes=None):
        client = make_client(routes or self.routes)
        with mock.patch("importer.tasks.make_client", return_value=client):
            result = import_feeds(*args)
        return result, client

    def test_imports_all_active_shops_in_order_and_returns_run_ids(self):
        run_ids, _ = self.run_task()
        self.assertEqual(run_ids, list(ImportRun.objects.order_by("pk").values_list("pk", flat=True)))
        self.assertEqual([run.shop for run in ImportRun.objects.order_by("pk")], [self.alpha, self.beta])
        self.assertEqual(Offer.objects.count(), 5)

    def test_one_shop_by_id(self):
        run_ids, _ = self.run_task(self.beta.pk)
        self.assertEqual(ImportRun.objects.get(pk=run_ids[0]).shop, self.beta)
        self.assertEqual((len(run_ids), Offer.objects.filter(shop=self.alpha).count()), (1, 0))

    def test_inactive_shop_is_skipped_even_when_asked_for_by_id(self):
        Shop.objects.filter(pk=self.alpha.pk).update(is_active=False)
        self.assertEqual(self.run_task(self.alpha.pk)[0], [])
        self.assertEqual(len(self.run_task()[0]), 1)

    def test_shop_without_feed_url_is_skipped(self):
        Shop.objects.filter(pk=self.alpha.pk).update(feed_url="")
        run_ids, _ = self.run_task()
        self.assertEqual([ImportRun.objects.get(pk=pk).shop for pk in run_ids], [self.beta])

    def test_unknown_shop_id(self):
        self.assertEqual(self.run_task(999999)[0], [])

    def test_nothing_to_import_does_not_open_a_connection(self):
        Shop.objects.update(is_active=False)
        with mock.patch("importer.tasks.make_client") as make:
            self.assertEqual(import_feeds(), [])
        make.assert_not_called()

    def test_connection_is_closed_afterwards(self):
        _, client = self.run_task()
        self.assertTrue(client.is_closed)

    def test_failed_shop_does_not_stop_the_others(self):
        routes = {self.alpha.feed_url: 500, self.beta.feed_url: many_offers_feed(3)}
        with self.assertLogs("importer", "WARNING"):
            run_ids, _ = self.run_task(routes=routes)
        statuses = [ImportRun.objects.get(pk=pk).status for pk in run_ids]
        self.assertEqual(statuses, ["failed", "success"])