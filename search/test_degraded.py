import itertools
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django_q.exceptions import TimeoutException
from django.urls import reverse
from django.utils import timezone

from search import degraded
from search.deadline import DELIVERY_BUDGET, SEARCH_DEADLINE, Deadline
from search.ranking import delivery_map, rank_and_save
from search.tasks import run_search
from search.views import _warnings

from .models import SearchRequest
from .test_ranking import RankingBase


class DeadlineTests(SimpleTestCase):
    def test_deadline_counts_from_the_given_start(self):
        with patch("search.deadline.time.monotonic", return_value=108.9):
            deadline = Deadline(SEARCH_DEADLINE, started=100.0)
            self.assertFalse(deadline.expired)
            self.assertAlmostEqual(deadline.remaining(), 0.1)
        with patch("search.deadline.time.monotonic", return_value=109.0):
            self.assertTrue(deadline.expired)
            self.assertEqual(deadline.remaining(), 0.0)

    def test_share_is_limited_by_what_is_left(self):
        deadline = Deadline(SEARCH_DEADLINE, started=0.0)
        with patch("search.deadline.time.monotonic", return_value=1.0):
            self.assertAlmostEqual(deadline.share(DELIVERY_BUDGET).remaining(), 3.0)
        with patch("search.deadline.time.monotonic", return_value=7.0):
            self.assertAlmostEqual(deadline.share(DELIVERY_BUDGET).remaining(), 2.0)
        with patch("search.deadline.time.monotonic", return_value=10.0):
            self.assertTrue(deadline.share(DELIVERY_BUDGET).expired)


class WarningMessagesTests(SimpleTestCase):
    def test_reasons_and_stale_shops_become_messages(self):
        facts = {"degraded_reasons": ["deadline", "delivery_failed"], "stale_shops": ["DNS"]}
        messages = degraded.warning_messages(facts)
        self.assertEqual(messages[:2], [degraded.MESSAGES["deadline"], degraded.MESSAGES["delivery_failed"]])
        self.assertIn("Данные магазина «DNS» не обновлялись больше 48 часов", messages[2])

    def test_several_stale_shops(self):
        self.assertIn("магазинов «DNS», «Ситилинк»", degraded.stale_message(["DNS", "Ситилинк"]))

    def test_nothing_to_warn_about(self):
        self.assertEqual(degraded.warning_messages({}), [])
        self.assertEqual(degraded.warning_messages({"degraded_reasons": ["unknown"], "stale_shops": []}), [])


class DeliveryDeadlineTests(RankingBase):
    def test_expired_deadline_skips_delivery_for_all_offers(self):
        reasons = set()
        with patch("delivery.services.calc_delivery") as calc:
            infos = delivery_map(self.offers, self.city, deadline=Deadline(0), degraded=reasons)
        calc.assert_not_called()
        self.assertEqual(infos, {offer.id: None for offer in self.offers})
        self.assertEqual(reasons, {degraded.DEADLINE_HIT})

    def test_delivery_stops_when_the_stage_budget_runs_out(self):
        clock = [0.0]

        def slow_calc(*args):
            clock[0] += 2.0
            return "info"

        reasons = set()
        offers = self.offers + [self.offer(self.fast, "31000")]
        with patch("search.deadline.time.monotonic", side_effect=lambda: clock[0]), \
                patch("delivery.services.calc_delivery", side_effect=slow_calc):
            infos = delivery_map(offers, self.city, degraded=reasons)
        self.assertEqual([infos[offer.id] for offer in offers], ["info", "info", None, None])
        self.assertEqual(reasons, {degraded.DEADLINE_HIT})

    def test_failing_offer_is_reported_as_failed_delivery(self):
        reasons = set()
        with patch("delivery.services.calc_delivery", side_effect=RuntimeError("сбой")), \
                self.assertLogs("search.ranking", "ERROR"):
            infos = delivery_map(self.offers, self.city, degraded=reasons)
        self.assertEqual(set(infos.values()), {None})
        self.assertEqual(reasons, {degraded.DELIVERY_FAILED})

    def test_rules_loading_failure_does_not_break_the_search(self):
        reasons = set()
        with patch("delivery.services.DeliveryContext", side_effect=RuntimeError("БД")), \
                self.assertLogs("search.ranking", "ERROR"):
            infos = delivery_map(self.offers, self.city, degraded=reasons)
        self.assertEqual(set(infos.values()), {None})
        self.assertEqual(reasons, {degraded.DELIVERY_FAILED})

    def test_guest_without_city_is_not_a_degradation(self):
        reasons = set()
        delivery_map(self.offers, None, degraded=reasons)
        self.assertEqual(reasons, set())


class DegradedSearchTests(RankingBase):
    def test_healthy_search_is_not_degraded(self):
        search = self.run_for()
        self.assertEqual((search.status, search.degraded, search.facts["degraded_reasons"]), ("done", False, []))

    def test_expired_deadline_still_returns_ranked_results(self):
        search = SearchRequest.objects.create(user=self.user, raw_query="смартфон", city=self.city)
        rank_and_save(search, list(self.offers), Deadline(0))
        search.refresh_from_db()
        self.assertTrue(search.degraded)
        self.assertEqual(search.facts["degraded_reasons"], ["deadline"])
        self.assertEqual(search.results.count(), 3)
        self.assertTrue(all(r.delivery_price is None for r in search.results.all()))
        self.assertIsNotNone(search.recommended_offer)

    def test_explanation_failure_keeps_the_recommendation(self):
        with patch("recommender.services.build_explanation", side_effect=RuntimeError("шаблон")), \
                self.assertLogs("search.ranking", "ERROR"):
            search = self.run_for()
        self.assertEqual(search.status, "done")
        self.assertTrue(search.degraded)
        self.assertEqual(search.facts["degraded_reasons"], ["explanation_failed"])
        self.assertEqual(search.explanation, "")
        self.assertIsNotNone(search.recommended_offer)

    def test_run_search_hands_a_deadline_to_the_pipeline(self):
        with patch("search.tasks.ranking.rank_and_save", return_value=0) as ranking:
            self.run_for()
        deadline = ranking.call_args.args[2]
        self.assertIsInstance(deadline, Deadline)
        self.assertLessEqual(deadline.remaining(), SEARCH_DEADLINE)

    def test_time_spent_in_the_queue_counts_against_the_deadline(self):
        search = SearchRequest.objects.create(user=self.user, raw_query="смартфон samsung", city=self.city)
        SearchRequest.objects.filter(pk=search.pk).update(created_at=timezone.now() - timedelta(seconds=10))
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            run_search(str(search.id))
        search.refresh_from_db()
        self.assertEqual((search.status, search.degraded), ("done", True))
        self.assertEqual(search.facts["degraded_reasons"], ["deadline"])
        self.assertTrue(all(r.delivery_price is None for r in search.results.all()))

    def test_search_killed_by_task_timeout_is_marked_failed_and_not_left_running(self):
        search = SearchRequest.objects.create(user=self.user, raw_query="смартфон", city=self.city)
        with patch("search.tasks.load_dictionaries", side_effect=TimeoutException("Task exceeded maximum timeout")), \
                self.assertRaises(SystemExit), self.assertLogs("search.tasks", "WARNING"):
            run_search(str(search.id))
        search.refresh_from_db()
        self.assertEqual((search.status, search.step), ("failed", ""))
        self.assertIsNotNone(search.finished_at)

    def test_overrun_is_logged(self):
        clock = itertools.chain([0.0], itertools.repeat(10.0))
        with patch("search.deadline.time.monotonic", side_effect=lambda: next(clock)), \
                self.assertLogs("search.tasks", "WARNING") as logs:
            self.run_for(city=None)
        self.assertIn("больше дедлайна", logs.output[0])


class StaleShopTests(RankingBase):
    def test_stale_shops_are_listed_in_facts(self):
        old = timezone.now() - timedelta(hours=49)
        self.fast.last_import_at = old
        self.fast.save()
        self.cheap.last_import_at = timezone.now() - timedelta(hours=1)
        self.cheap.save()
        search = self.run_for()
        self.assertEqual(search.facts["stale_shops"], ["Быстрый"])

    def test_shops_never_imported_are_not_reported(self):
        self.assertEqual(self.run_for().facts["stale_shops"], [])

    def test_warnings_reach_the_results_page(self):
        self.fast.last_import_at = timezone.now() - timedelta(days=3)
        self.fast.save()
        search = self.run_for()
        self.client.force_login(self.user)
        html = self.client.get(reverse("search:results", args=[search.id])).content.decode()
        self.assertIn("Данные магазина «Быстрый» не обновлялись больше 48 часов", html)

    def test_criterion_switch_keeps_stale_warning_and_recomputes_degradation(self):
        self.fast.last_import_at = timezone.now() - timedelta(days=3)
        self.fast.save()
        search = self.run_for()
        self.client.force_login(self.user)
        url = reverse("search:results_api", args=[search.id])
        with patch("delivery.services.calc_delivery", side_effect=RuntimeError("сбой")), \
                self.assertLogs("search.ranking", "ERROR"):
            self.client.get(url, {"criterion": "speed"})
        search.refresh_from_db()
        self.assertTrue(search.degraded)
        self.assertEqual(search.facts["stale_shops"], ["Быстрый"])
        self.client.get(url, {"criterion": "price"})
        search.refresh_from_db()
        self.assertFalse(search.degraded)
        self.assertEqual(search.facts["degraded_reasons"], [])

    def test_warnings_helper_combines_budget_and_degradation(self):
        search = SearchRequest(facts={"degraded_reasons": ["deadline"]}, status="done")
        self.assertEqual(_warnings(search, [object()]), [degraded.MESSAGES["deadline"]])
