from datetime import timedelta
from unittest import mock
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from catalog.models import Offer
from importer import downloader
from importer.downloader import DownloadError, download_feed, is_transient
from django_q.exceptions import TimeoutException

from importer.lifecycle import RUN_ABANDONED_AFTER
from importer.models import ImportRun
from importer.offer_writer import write_offers

from .helpers import NoRetryPause, do_import, feed_xml, make_shop, normalize, offer_xml

URL = "http://shop.example/feed.yml"


def feed_of(*ids, bad=0):
    return feed_xml(*(offer_xml(i, model=f"Модель {i}", vendorCode=f"SM-{i}") for i in ids),
                    *(offer_xml(f"bad{n}", price=None) for n in range(bad)))


def scripted_client(*steps):
    steps = list(steps)

    def handler(request):
        step = steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, int):
            return httpx.Response(step)
        return httpx.Response(200, content=step)
    return httpx.Client(transport=httpx.MockTransport(handler)), steps


class DownloadRetryTests(SimpleTestCase):
    def fetch(self, *steps):
        client, left = scripted_client(*steps)
        with mock.patch("importer.downloader.time.sleep") as sleep, download_feed(URL, client) as feed:
            return feed.read(), sleep, left

    def test_transient_failures_are_retried_with_growing_pauses(self):
        data, sleep, left = self.fetch(httpx.ConnectError("нет связи"), 503, b"<ok/>")
        self.assertEqual((data, left), (b"<ok/>", []))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 3.0])

    def test_client_errors_are_not_retried(self):
        client, left = scripted_client(404, b"<ok/>")
        with mock.patch("importer.downloader.time.sleep") as sleep, \
                self.assertRaises(httpx.HTTPStatusError), download_feed(URL, client):
            pass
        sleep.assert_not_called()
        self.assertEqual(len(left), 1)

    def test_error_is_raised_after_last_attempt(self):
        client, left = scripted_client(500, 502, 504)
        with mock.patch("importer.downloader.time.sleep") as sleep, \
                self.assertRaises(httpx.HTTPStatusError) as caught, download_feed(URL, client):
            pass
        self.assertEqual(caught.exception.response.status_code, 504)
        self.assertEqual((sleep.call_count, left), (2, []))

    def test_partial_download_is_discarded_on_retry(self):
        def broken_stream():
            yield b"x" * 100
            raise httpx.ReadError("обрыв")
        data, _, _ = self.fetch(broken_stream(), b"<ok/>")
        self.assertEqual(data, b"<ok/>")

    def test_which_errors_are_transient(self):
        request = httpx.Request("GET", URL)
        self.assertTrue(is_transient(httpx.ReadTimeout("")))
        self.assertTrue(is_transient(httpx.ConnectError("")))
        self.assertTrue(is_transient(httpx.HTTPStatusError("", request=request, response=httpx.Response(429))))
        self.assertFalse(is_transient(httpx.HTTPStatusError("", request=request, response=httpx.Response(403))))
        self.assertFalse(is_transient(httpx.UnsupportedProtocol("ftp")))

    def test_too_large_feed_is_rejected_without_retry(self):
        client, left = scripted_client(b"x" * 100, b"y")
        with mock.patch.object(downloader, "MAX_FEED_BYTES", 10), \
                mock.patch("importer.downloader.time.sleep") as sleep, \
                self.assertRaisesMessage(DownloadError, "МБ"), download_feed(URL, client):
            pass
        sleep.assert_not_called()
        self.assertEqual(len(left), 1)

    def test_too_slow_download_is_rejected_without_retry(self):
        def trickle():
            yield b"a"
            yield b"b"
            raise AssertionError("поток читался после превышения лимита")
        client, left = scripted_client(trickle(), b"y")
        with mock.patch("importer.downloader.time.monotonic", side_effect=[0.0, 100.0]), \
                mock.patch("importer.downloader.time.sleep") as sleep, \
                self.assertRaisesMessage(DownloadError, "дольше"), download_feed(URL, client):
            pass
        sleep.assert_not_called()
        self.assertEqual(len(left), 1)


class ImportStatusTests(NoRetryPause, TestCase):
    def setUp(self):
        self.shop = make_shop()

    def active(self):
        return set(Offer.objects.filter(shop=self.shop, is_active=True).values_list("external_id", flat=True))

    def test_many_skipped_records_make_the_run_partial(self):
        run = do_import(self.shop, feed_of("1", "2", "3", bad=2))
        self.assertEqual((run.status, run.stats["created"], run.stats["errors"]), ("partial", 3, 2))
        self.assertIn("2 из 5", run.error)
        self.shop.refresh_from_db()
        self.assertIsNotNone(self.shop.last_import_at)

    def test_share_of_errors_at_the_threshold_is_still_success(self):
        run = do_import(self.shop, feed_of("1", "2", "3", "4", bad=1))
        self.assertEqual(run.status, "success")

    def test_failed_run_leaves_last_import_time_untouched(self):
        do_import(self.shop, feed_of("1"))
        self.shop.refresh_from_db()
        before = self.shop.last_import_at
        self.assertEqual(do_import(self.shop, 500).status, "failed")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.last_import_at, before)


class DeactivationTests(NoRetryPause, TestCase):
    def setUp(self):
        self.shop = make_shop()

    def active(self):
        return set(Offer.objects.filter(shop=self.shop, is_active=True).values_list("external_id", flat=True))

    def test_offer_is_deactivated_after_two_runs_without_it(self):
        do_import(self.shop, feed_of("a", "b", "c"))
        do_import(self.shop, feed_of("a", "b"))
        self.assertEqual(self.active(), {"a", "b", "c"})
        run = do_import(self.shop, feed_of("a", "b"))
        self.assertEqual(self.active(), {"a", "b"})
        self.assertEqual((run.status, run.stats["deactivated"]), ("success", 1))
        self.assertIn("деактивировано 1", run.summary())

    def test_first_successful_run_deactivates_nothing(self):
        Offer.objects.create(shop=self.shop, external_id="old", url="http://x", title_raw="t", price=1,
                             last_seen_at=timezone.now() - timedelta(days=30))
        do_import(self.shop, feed_of("a"))
        self.assertEqual(self.active(), {"old", "a"})

    def test_returning_offer_is_reactivated(self):
        do_import(self.shop, feed_of("a", "b"))
        do_import(self.shop, feed_of("a"))
        do_import(self.shop, feed_of("a"))
        self.assertEqual(self.active(), {"a"})
        run = do_import(self.shop, feed_of("a", "b"))
        self.assertEqual(self.active(), {"a", "b"})
        self.assertEqual(run.stats["reactivated"], 1)

    def test_manually_hidden_offer_stays_hidden_while_it_is_in_the_feed(self):
        do_import(self.shop, feed_of("a", "b"))
        Offer.objects.filter(external_id="b").update(is_active=False)
        for _ in range(3):
            do_import(self.shop, feed_of("a", "b"))
        self.assertEqual(self.active(), {"a"})

    def test_partial_run_does_not_deactivate(self):
        do_import(self.shop, feed_of("a", "b", "c"))
        do_import(self.shop, feed_of("a"))
        run = do_import(self.shop, feed_of("a", bad=2))
        self.assertEqual(run.status, "partial")
        self.assertEqual(self.active(), {"a", "b", "c"})

    def test_failed_run_does_not_deactivate(self):
        do_import(self.shop, feed_of("a", "b"))
        do_import(self.shop, feed_of("a"))
        do_import(self.shop, 500)
        self.assertEqual(self.active(), {"a", "b"})

    def test_mass_disappearance_is_applied_and_reverted_when_the_feed_returns(self):
        ids = [str(i) for i in range(12)]
        do_import(self.shop, feed_of(*ids))
        do_import(self.shop, feed_of("0"))
        run = do_import(self.shop, feed_of("0"))
        self.assertEqual((run.status, run.stats["deactivated"], self.active()), ("success", 11, {"0"}))
        run = do_import(self.shop, feed_of(*ids))
        self.assertEqual((run.stats["reactivated"], len(self.active())), (11, 12))

    def test_failure_while_finishing_marks_the_run_failed_instead_of_leaving_it_running(self):
        do_import(self.shop, feed_of("a"))
        with patch("importer.services.deactivate_missing", side_effect=RuntimeError("БД")):
            run = do_import(self.shop, feed_of("a"))
        run.refresh_from_db()
        self.assertEqual((run.status, run.error), ("failed", "RuntimeError: БД"))
        self.assertIsNotNone(run.finished_at)


class RunLifecycleTests(NoRetryPause, TestCase):
    def setUp(self):
        self.shop = make_shop()

    def test_fresh_running_run_blocks_a_second_import(self):
        running = ImportRun.objects.create(shop=self.shop)
        client, left = scripted_client(feed_of("a"))
        self.assertEqual(self.import_with(client), running)
        self.assertEqual((len(left), ImportRun.objects.count(), Offer.objects.count()), (1, 1, 0))

    def test_abandoned_running_run_is_closed_and_import_proceeds(self):
        stuck = ImportRun.objects.create(shop=self.shop)
        long_ago = timezone.now() - RUN_ABANDONED_AFTER - timedelta(minutes=1)
        ImportRun.objects.filter(pk=stuck.pk).update(started_at=long_ago)
        run = do_import(self.shop, feed_of("a"))
        stuck.refresh_from_db()
        self.assertEqual((stuck.status, run.status), ("failed", "success"))
        self.assertIn("прерван", stuck.error)
        self.assertIsNotNone(stuck.finished_at)

    def test_import_killed_by_task_timeout_is_closed_as_failed_and_not_left_running(self):
        with patch("importer.services._import_feed", side_effect=TimeoutException("Task exceeded maximum timeout")), \
                self.assertRaises(SystemExit), self.assertLogs("importer.services", "WARNING"):
            do_import(self.shop, feed_of("a"))
        run = ImportRun.objects.get(shop=self.shop)
        self.assertEqual(run.status, "failed")
        self.assertIn("Task exceeded maximum timeout", run.error)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(do_import(self.shop, feed_of("a")).status, "success")

    def test_manual_interrupt_is_also_recorded(self):
        with patch("importer.services._import_feed", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt), self.assertLogs("importer.services", "WARNING"):
            do_import(self.shop, feed_of("a"))
        self.assertEqual(ImportRun.objects.get(shop=self.shop).error, "Импорт прерван: KeyboardInterrupt")

    def test_other_shops_runs_do_not_block(self):
        ImportRun.objects.create(shop=make_shop("Другой"))
        self.assertEqual(do_import(self.shop, feed_of("a")).status, "success")

    def import_with(self, client):
        from importer.services import import_shop
        with client:
            return import_shop(self.shop, client)


class ReactivationWriterTests(TestCase):
    def setUp(self):
        self.shop = make_shop()
        self.now = timezone.now()

    def test_only_offers_absent_before_the_threshold_are_reactivated(self):
        write_offers(self.shop, [normalize(id="gone"), normalize(id="hidden")], self.now - timedelta(days=2))
        Offer.objects.filter(external_id="gone").update(is_active=False, last_seen_at=self.now - timedelta(days=2))
        Offer.objects.filter(external_id="hidden").update(is_active=False, last_seen_at=self.now - timedelta(hours=1))
        stats = write_offers(self.shop, [normalize(id="gone", price="1"), normalize(id="hidden")], self.now,
                             reactivate_before=self.now - timedelta(hours=6))
        self.assertEqual(stats.reactivated, 1)
        self.assertEqual(dict(Offer.objects.values_list("external_id", "is_active")), {"gone": True, "hidden": False})

    def test_without_threshold_nothing_is_reactivated(self):
        write_offers(self.shop, [normalize()], self.now - timedelta(days=2))
        Offer.objects.update(is_active=False)
        stats = write_offers(self.shop, [normalize()], self.now)
        self.assertEqual(stats.reactivated, 0)
        self.assertFalse(Offer.objects.get().is_active)
