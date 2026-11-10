from contextlib import nullcontext
from unittest import mock

import httpx
from django.test import TestCase

from catalog.models import Offer, PriceHistory, Shop
from importer.models import ImportRun
from importer.services import MAX_ERROR_SAMPLES
from importer.tasks import import_feeds

from .helpers import do_import, feed_xml, make_client, make_shop, many_offers_feed, offer_xml


class ImportShopTests(TestCase):
    def setUp(self):
        self.shop = make_shop()

    def test_imports_valid_offers_and_records_run(self):
        run = do_import(self.shop, many_offers_feed(5))
        run = ImportRun.objects.get(pk=run.pk)
        self.assertEqual(run.shop, self.shop)
        self.assertEqual(run.status, "success")
        self.assertEqual(run.error, "")
        self.assertEqual((run.stats["created"], run.stats["updated"], run.stats["unchanged"], run.stats["errors"]),
                         (5, 0, 0, 0))
        self.assertEqual(run.summary(), "создано 5, обновлено 0, без изменений 0, ошибок 0")
        self.assertGreaterEqual(run.finished_at, run.started_at)
        self.assertEqual(Offer.objects.filter(shop=self.shop).count(), 5)
        self.assertEqual(PriceHistory.objects.count(), 5)

    def test_last_import_at_is_set_on_success(self):
        self.assertIsNone(self.shop.last_import_at)
        run = do_import(self.shop, many_offers_feed(1))
        self.shop.refresh_from_db()
        self.assertTrue(run.started_at <= self.shop.last_import_at <= run.finished_at)

    def test_offers_get_last_seen_equal_to_run_start(self):
        run = do_import(self.shop, many_offers_feed(3))
        self.assertEqual(set(Offer.objects.values_list("last_seen_at", flat=True)), {run.started_at})

    def test_second_run_changes_nothing(self):
        feed = many_offers_feed(4)
        do_import(self.shop, feed)
        run = do_import(self.shop, feed)
        self.assertEqual((run.stats["created"], run.stats["updated"], run.stats["unchanged"]), (0, 0, 4))
        self.assertEqual(PriceHistory.objects.count(), 4)

    def test_changed_price_in_feed_is_picked_up(self):
        do_import(self.shop, feed_xml(offer_xml("1", price="1000"), offer_xml("2", price="2000")))
        run = do_import(self.shop, feed_xml(offer_xml("1", price="900"), offer_xml("2", price="2000")))
        self.assertEqual((run.stats["created"], run.stats["updated"], run.stats["unchanged"]), (0, 1, 1))
        offer = Offer.objects.get(external_id="1")
        self.assertEqual(str(offer.price), "900.00")
        self.assertEqual([str(p) for p in offer.history.order_by("pk").values_list("price", flat=True)],
                         ["1000.00", "900.00"])

    def test_skipped_records_are_counted_logged_and_sampled(self):
        feed = feed_xml(offer_xml("ok"), offer_xml("no-price", price=None), offer_xml("bad-cat", categoryId="999"))
        with self.assertLogs("importer", "WARNING") as logs:
            run = do_import(self.shop, feed)
        self.assertEqual((run.stats["created"], run.stats["errors"]), (1, 2))
        self.assertEqual(run.stats["error_samples"], ["no-price: нет цены", "bad-cat: категория '999' не сопоставлена"])
        text = "\n".join(logs.output)
        self.assertIn("no-price пропущено: нет цены", text)
        self.assertIn("bad-cat пропущено: категория '999' не сопоставлена", text)

    def test_error_samples_are_capped(self):
        broken = [offer_xml(str(i), price=None) for i in range(MAX_ERROR_SAMPLES + 5)]
        with self.assertLogs("importer", "WARNING"):
            run = do_import(self.shop, feed_xml(offer_xml("ok"), *broken))
        self.assertEqual(run.stats["errors"], MAX_ERROR_SAMPLES + 5)
        self.assertEqual(len(run.stats["error_samples"]), MAX_ERROR_SAMPLES)
        self.assertEqual(run.stats["error_samples"][0], "0: нет цены")

    def test_duplicate_id_in_feed_keeps_first_offer(self):
        feed = feed_xml(offer_xml("1", price="100"), offer_xml("1", price="999"))
        with self.assertLogs("importer", "WARNING"):
            run = do_import(self.shop, feed)
        self.assertEqual((run.stats["created"], run.stats["errors"]), (1, 1))
        self.assertEqual(str(Offer.objects.get().price), "100.00")


class ImportFailureTests(TestCase):
    def setUp(self):
        self.shop = make_shop()

    def failed(self, response):
        self.shop.refresh_from_db()
        last_import_at = self.shop.last_import_at
        with self.assertLogs("importer", "WARNING"):
            run = do_import(self.shop, response)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIsNotNone(run.finished_at)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.last_import_at, last_import_at)
        return run

    def test_http_error(self):
        self.assertIn("500", self.failed(500).error)

    def test_http_error_text_is_one_line(self):
        error = self.failed(404).error
        self.assertNotIn("\n", error)
        self.assertIn("404 Not Found", error)

    def test_network_error(self):
        self.assertIn("ConnectError: нет связи", self.failed(httpx.ConnectError("нет связи")).error)

    def test_timeout_without_message_still_has_readable_error(self):
        self.assertIn("ReadTimeout", self.failed(httpx.ReadTimeout("")).error)

    def test_broken_xml(self):
        self.assertIn("ParseError", self.failed(many_offers_feed(3)[:-60]).error)

    def test_not_a_feed(self):
        page = "<html><body>Технические работы</body></html>".encode()
        self.assertIn("нет ни одного предложения", self.failed(page).error)

    def test_empty_feed(self):
        self.assertIn("нет ни одного предложения", self.failed(feed_xml()).error)

    def test_failed_run_keeps_previous_data(self):
        do_import(self.shop, many_offers_feed(3))
        before = list(Offer.objects.order_by("pk").values())

        self.failed(503)

        self.assertEqual(list(Offer.objects.order_by("pk").values()), before)

    def test_xml_broken_in_the_middle_changes_nothing(self):
        do_import(self.shop, feed_xml(offer_xml("0", price="100"), offer_xml("1", price="200")))
        before = (list(Offer.objects.order_by("pk").values()), PriceHistory.objects.count())

        offers = [offer_xml("0", price="150"), offer_xml("1", price="250")]
        offers += [offer_xml(str(i)) for i in range(2, 1300)]   # больше двух пачек по 500
        run = self.failed(feed_xml(*offers)[:-100])

        self.assertIn("ParseError", run.error)
        self.assertEqual((list(Offer.objects.order_by("pk").values()), PriceHistory.objects.count()), before)

    def test_unexpected_error_is_recorded_not_raised(self):
        with self.assertLogs("importer", "ERROR") as logs, \
                mock.patch("importer.services.write_offers", side_effect=RuntimeError("сбой")):
            run = do_import(self.shop, many_offers_feed(2))
        run.refresh_from_db()
        self.assertEqual((run.status, run.error), ("failed", "RuntimeError: сбой"))
        self.assertIsNotNone(logs.records[0].exc_info)  # для неожиданных ошибок traceback нужен

    def test_expected_failures_are_logged_as_warning_without_traceback(self):
        with self.assertLogs("importer", "WARNING") as logs:
            do_import(self.shop, 500)
        self.assertEqual([record.levelname for record in logs.records], ["WARNING"])
        self.assertIsNone(logs.records[0].exc_info)

    def test_run_after_failure_succeeds(self):
        with self.assertLogs("importer", "WARNING"):
            do_import(self.shop, 500)
        run = do_import(self.shop, many_offers_feed(2))
        self.assertEqual(run.status, "success")
        self.assertEqual(ImportRun.objects.filter(shop=self.shop).count(), 2)


class ImportFeedsTaskTests(TestCase):
    def setUp(self):
        self.first = make_shop("Первый")
        self.second = make_shop("Второй")

    def call(self, *args, routes=None, warnings=False):
        routes = routes or {self.first.feed_url: many_offers_feed(2), self.second.feed_url: many_offers_feed(3)}
        logs = self.assertLogs("importer", "WARNING") if warnings else nullcontext()
        with mock.patch("importer.tasks.make_client", return_value=make_client(routes)), logs:
            return import_feeds(*args)

    def test_all_active_shops(self):
        run_ids = self.call()
        runs = ImportRun.objects.filter(pk__in=run_ids).order_by("pk")
        self.assertEqual([run.shop for run in runs], [self.first, self.second])
        self.assertEqual({run.status for run in runs}, {"success"})

    def test_single_shop_by_id(self):
        run_ids = self.call(self.second.pk)
        self.assertEqual([ImportRun.objects.get(pk=pk).shop for pk in run_ids], [self.second])
        self.assertEqual(Offer.objects.filter(shop=self.first).count(), 0)

    def test_inactive_shop_is_skipped(self):
        Shop.objects.filter(pk=self.second.pk).update(is_active=False)
        self.assertEqual(self.call(self.second.pk), [])
        self.assertEqual(len(self.call()), 1)

    def test_shop_without_feed_url_is_skipped(self):
        Shop.objects.filter(pk=self.second.pk).update(feed_url="")
        self.assertEqual(len(self.call()), 1)

    def test_unknown_shop_gives_nothing(self):
        self.assertEqual(self.call(999999), [])
        self.assertEqual(ImportRun.objects.count(), 0)

    def test_one_failing_shop_does_not_stop_the_others(self):
        routes = {self.first.feed_url: 500, self.second.feed_url: many_offers_feed(3)}
        run_ids = self.call(routes=routes, warnings=True)
        statuses = {run.shop.name: run.status for run in ImportRun.objects.filter(pk__in=run_ids)}
        self.assertEqual(statuses, {"Первый": "failed", "Второй": "success"})