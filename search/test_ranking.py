from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Category, Offer, Product, Shop
from delivery.models import City, ShopDeliveryRule
from delivery.services import DeliveryInfo

from .models import SearchRequest
from .tasks import run_search


class RankingBase(TestCase):
    def setUp(self):
        self.city = City.objects.create(name="Екатеринбург", zone=1)
        category = Category.objects.create(name="Смартфоны", slug="smartphones", keywords="смартфон")
        self.product = Product.objects.create(category=category, name="Samsung Galaxy A55")
        self.fast = Shop.objects.create(name="Быстрый", rating=Decimal("4.6"), rating_count=200)
        self.cheap = Shop.objects.create(name="Дешёвый", rating=Decimal("4.2"), rating_count=50)
        self.plain = Shop.objects.create(name="Без правил")
        ShopDeliveryRule.objects.create(shop=self.fast, city=None, cost=0, min_days=1, max_days=1)
        ShopDeliveryRule.objects.create(shop=self.cheap, city=None, cost=300, min_days=4, max_days=5)
        self.o_fast = self.offer(self.fast, "30000")
        self.o_cheap = self.offer(self.cheap, "27000")
        self.o_plain = self.offer(self.plain, "28000")
        self.offers = [self.o_fast, self.o_cheap, self.o_plain]
        self.user = User.objects.create_user("buyer", "buyer@example.com", "Str0ng-pass-123", city=self.city)

    def offer(self, shop, price):
        return Offer.objects.create(
            product=self.product, shop=shop, external_id=f"{shop.pk}-{price}",
            url="https://shop.example/item", title_raw=f"Samsung Galaxy A55 ({shop.name})", price=Decimal(price))

    def run_for(self, user=None, city="default", query="смартфон samsung"):
        user = user or self.user
        search = SearchRequest.objects.create(
            user=user, raw_query=query, city=self.city if city == "default" else city)
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            run_search(str(search.id))
        search.refresh_from_db()
        return search

    def set_priority(self, priority, budget=None):
        self.user.delivery_priority = priority
        self.user.budget_max = budget
        self.user.save()


class DeliveryStubTests(RankingBase):
    def result_for(self, search, offer):
        return search.results.get(offer=offer)

    def test_shop_rules_fill_delivery(self):
        search = self.run_for()
        fast = self.result_for(search, self.o_fast)
        cheap = self.result_for(search, self.o_cheap)
        self.assertEqual((fast.delivery_price, fast.delivery_min_days, fast.delivery_max_days), (0, 1, 1))
        self.assertEqual((cheap.delivery_price, cheap.delivery_min_days, cheap.delivery_max_days), (300, 4, 5))
        self.assertEqual(fast.delivery_source, "shop")

    def test_total_includes_delivery(self):
        search = self.run_for()
        self.assertEqual(self.result_for(search, self.o_cheap).total_price, Decimal("27300"))
        self.assertEqual(self.result_for(search, self.o_fast).total_price, Decimal("30000"))

    def test_shop_without_rules_has_unknown_delivery(self):
        result = self.result_for(self.run_for(), self.o_plain)
        self.assertIsNone(result.delivery_price)
        self.assertEqual(result.total_price, Decimal("28000"))

    def test_free_delivery_threshold(self):
        ShopDeliveryRule.objects.filter(shop=self.cheap).update(free_from=Decimal("25000"))
        self.assertEqual(self.result_for(self.run_for(), self.o_cheap).delivery_price, 0)

    def test_city_rule_beats_default_rule(self):
        ShopDeliveryRule.objects.create(shop=self.cheap, city=self.city, cost=100, min_days=2, max_days=2)
        result = self.result_for(self.run_for(), self.o_cheap)
        self.assertEqual((result.delivery_price, result.delivery_max_days), (100, 2))

    def test_rule_of_other_city_is_ignored(self):
        other = City.objects.create(name="Москва", zone=2)
        ShopDeliveryRule.objects.filter(shop=self.cheap).delete()
        ShopDeliveryRule.objects.create(shop=self.cheap, city=other, cost=50, min_days=1, max_days=1)
        self.assertIsNone(self.result_for(self.run_for(), self.o_cheap).delivery_price)

    def test_without_city_delivery_is_unknown(self):
        search = self.run_for(city=None)
        self.assertTrue(all(r.delivery_price is None for r in search.results.all()))
        self.assertTrue(all(r.total_price == r.item_price for r in search.results.all()))

    def test_real_calc_delivery_is_used_when_implemented(self):
        info = DeliveryInfo(price=Decimal("700"), min_days=2, max_days=3, source="cdek")
        with patch("delivery.services.calc_delivery", return_value=info):
            search = self.run_for()
        result = self.result_for(search, self.o_fast)
        self.assertEqual((result.delivery_price, result.delivery_source), (700, "cdek"))

    def test_delivery_error_is_isolated(self):
        def broken(offer, city):
            if offer.pk == self.o_cheap.pk:
                raise RuntimeError("boom")
            return DeliveryInfo(price=Decimal("100"), min_days=1, max_days=2, source="cdek")
        with patch("delivery.services.calc_delivery", side_effect=broken), \
                self.assertLogs("search.ranking", level="ERROR"):
            search = self.run_for()
        self.assertEqual(search.status, "done")
        self.assertIsNone(self.result_for(search, self.o_cheap).delivery_price)
        self.assertEqual(self.result_for(search, self.o_fast).delivery_price, 100)


class RecommendationTests(RankingBase):
    def winner(self, priority, budget=None):
        self.set_priority(priority, budget)
        return self.run_for().recommended_offer

    def test_priority_from_profile_selects_winner(self):
        self.assertEqual(self.winner("price"), self.o_cheap)
        self.assertEqual(self.winner("speed"), self.o_fast)
        self.assertEqual(self.winner("balanced"), self.o_plain)

    def test_anonymous_search_uses_balanced(self):
        search = SearchRequest.objects.create(raw_query="смартфон", session_key="s", city=self.city)
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            run_search(str(search.id))
        search.refresh_from_db()
        self.assertEqual(search.facts["criterion"], "balanced")

    def test_recommendation_is_saved(self):
        self.set_priority("price")
        search = self.run_for()
        self.assertEqual(search.recommended_offer, self.o_cheap)
        self.assertIn("Дешёвый", search.explanation)
        self.assertIn("27\u00a0300", search.explanation)
        self.assertEqual(search.facts["criterion"], "price")
        self.assertEqual(search.facts["total_price"], 27300.0)
        self.assertEqual(list(search.results.values_list("is_recommended", flat=True)).count(True), 1)
        self.assertTrue(search.results.get(offer=self.o_cheap).is_recommended)

    def test_results_have_score_and_breakdown(self):
        search = self.run_for()
        for result in search.results.all():
            self.assertGreater(result.score, 0)
            self.assertEqual(set(result.breakdown), {"price", "speed", "reliability", "weights"})

    def test_rank_follows_score(self):
        search = self.run_for()
        scores = list(search.results.order_by("rank").values_list("score", flat=True))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_profile_budget_excludes_expensive_offers(self):
        self.set_priority("price", Decimal("27500"))
        search = self.run_for()
        self.assertEqual(list(search.results.values_list("offer_id", flat=True)), [self.o_cheap.id])
        self.assertEqual(search.facts["excluded_over_budget"], 2)

    def test_budget_below_everything_gives_warning(self):
        self.set_priority("price", Decimal("1000"))
        search = self.run_for()
        self.assertEqual(search.results.count(), 0)
        self.assertIsNone(search.recommended_offer)
        self.client.force_login(self.user)
        response = self.client.get(reverse("search:results", args=[search.id]))
        self.assertEqual(len(response.context["warnings"]), 1)
        self.assertIn("дороже вашего бюджета", response.context["warnings"][0])

    def test_repeated_run_keeps_single_recommendation(self):
        search = self.run_for()
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            run_search(str(search.id))
        self.assertEqual(search.results.count(), 3)
        self.assertEqual(search.results.filter(is_recommended=True).count(), 1)


class CriterionSwitchTests(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)
        self.url = reverse("search:results", args=[self.search.id])

    def test_default_criterion_is_shown(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["criterion"], "balanced")
        self.assertEqual([value for value, _ in response.context["criteria"]], ["balanced", "price", "speed"])

    def test_switching_recalculates_recommendation(self):
        response = self.client.get(self.url, {"criterion": "speed"})
        self.search.refresh_from_db()
        self.assertEqual(self.search.recommended_offer, self.o_fast)
        self.assertEqual(self.search.facts["criterion"], "speed")
        self.assertEqual(response.context["recommendation"]["offer_id"], self.o_fast.id)
        self.assertIn("самая быстрая доставка", response.context["recommendation"]["explanation"])
        flags = {r.offer_id: r.is_recommended for r in self.search.results.all()}
        self.assertEqual(flags, {self.o_fast.id: True, self.o_cheap.id: False, self.o_plain.id: False})

    def test_switch_is_persistent(self):
        self.client.get(self.url, {"criterion": "price"})
        response = self.client.get(self.url)
        self.assertEqual(response.context["criterion"], "price")
        self.assertEqual(response.context["recommendation"]["offer_id"], self.o_cheap.id)

    def test_switch_back_and_forth(self):
        for criterion, expected in (("price", self.o_cheap), ("speed", self.o_fast), ("balanced", self.o_plain)):
            self.client.get(self.url, {"criterion": criterion})
            self.search.refresh_from_db()
            self.assertEqual(self.search.recommended_offer, expected)

    def test_default_order_follows_recommendation(self):
        self.client.get(self.url, {"criterion": "speed"})
        items = self.client.get(self.url).context["items"]
        self.assertEqual(items[0]["offer_id"], self.o_fast.id)
        self.assertTrue(items[0]["is_recommended"])

    def test_invalid_criterion_is_ignored(self):
        self.client.get(self.url, {"criterion": "nonsense"})
        self.search.refresh_from_db()
        self.assertEqual(self.search.facts["criterion"], "balanced")

    def test_switch_keeps_budget_facts(self):
        self.client.get(self.url, {"criterion": "price"})
        self.search.refresh_from_db()
        self.assertIn("excluded_over_budget", self.search.facts)

    def test_page_shows_recommendation_and_selector(self):
        html = self.client.get(self.url, {"criterion": "price"}).content.decode()
        self.assertIn("Рекомендация", html)
        self.assertIn("Дешёвый", html)
        self.assertIn('name="criterion"', html)
        self.assertIn("Скорость", html)


class SortAndFilterTests(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)
        self.url = reverse("search:results", args=[self.search.id])

    def order(self, **params):
        return [i["offer_id"] for i in self.client.get(self.url, params).context["items"]]

    def test_default_order_is_rank(self):
        expected = list(self.search.results.order_by("rank").values_list("offer_id", flat=True))
        self.assertEqual(self.order(), expected)

    def test_sort_by_price(self):
        self.assertEqual(self.order(sort="price"), [self.o_cheap.id, self.o_plain.id, self.o_fast.id])

    def test_sort_by_total(self):
        self.assertEqual(self.order(sort="total"), [self.o_cheap.id, self.o_plain.id, self.o_fast.id])

    def test_sort_by_delivery_puts_unknown_last(self):
        self.assertEqual(self.order(sort="delivery"), [self.o_fast.id, self.o_cheap.id, self.o_plain.id])

    def test_sort_by_rating_puts_unrated_last(self):
        self.assertEqual(self.order(sort="rating"), [self.o_fast.id, self.o_cheap.id, self.o_plain.id])

    def test_unknown_sort_falls_back_to_rank(self):
        self.assertEqual(self.order(sort="nonsense"), self.order())

    def test_filter_price_max(self):
        self.assertEqual(set(self.order(price_max="28000")), {self.o_cheap.id, self.o_plain.id})

    def test_filter_delivery_max_days(self):
        self.assertEqual(self.order(delivery_max_days="1"), [self.o_fast.id])

    def test_filter_with_sort(self):
        self.assertEqual(self.order(price_max="28000", sort="price"), [self.o_cheap.id, self.o_plain.id])

    def test_garbage_filters_are_ignored(self):
        self.assertEqual(len(self.order(price_max="abc", delivery_max_days="-3")), 3)

    def test_selected_sort_is_passed_to_template(self):
        self.assertEqual(self.client.get(self.url, {"sort": "rating"}).context["sort"], "rating")
        self.assertEqual(self.client.get(self.url).context["sort"], "")

    def test_rating_is_shown_in_items(self):
        items = {i["offer_id"]: i for i in self.client.get(self.url).context["items"]}
        self.assertEqual(items[self.o_fast.id]["rating"], Decimal("4.60"))
        self.assertIsNone(items[self.o_plain.id]["rating"])


class ResultsApiTests(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)
        self.url = reverse("search:results_api", args=[self.search.id])

    def test_structure(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual(set(data), {"status", "criterion", "sort", "recommendation", "count", "items"})
        self.assertEqual((data["status"], data["count"], data["sort"]), ("done", 3, "recommendation"))
        self.assertEqual(set(data["items"][0]), {
            "offer_id", "shop", "title", "price", "delivery_price", "delivery_min_days", "delivery_max_days",
            "total_price", "rating", "rank", "score", "is_recommended", "url"})

    def test_numbers_are_numeric(self):
        item = next(i for i in self.client.get(self.url).json()["items"] if i["offer_id"] == self.o_cheap.id)
        self.assertEqual((item["price"], item["delivery_price"], item["total_price"]), (27000.0, 300.0, 27300.0))
        self.assertEqual((item["delivery_min_days"], item["delivery_max_days"], item["rating"]), (4, 5, 4.2))
        self.assertEqual(item["url"], reverse("search:go", args=[self.o_cheap.id]))

    def test_unknown_values_are_null(self):
        item = next(i for i in self.client.get(self.url).json()["items"] if i["offer_id"] == self.o_plain.id)
        self.assertIsNone(item["delivery_price"])
        self.assertIsNone(item["rating"])

    def test_recommendation_block(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data["recommendation"]["offer_id"], self.o_plain.id)
        self.assertTrue(data["recommendation"]["explanation"])
        self.assertEqual(data["recommendation"]["facts"]["criterion"], "balanced")

    def test_sorting(self):
        for sort, expected in (
            ("price", [self.o_cheap, self.o_plain, self.o_fast]),
            ("delivery", [self.o_fast, self.o_cheap, self.o_plain]),
            ("rating", [self.o_fast, self.o_cheap, self.o_plain]),
        ):
            with self.subTest(sort=sort):
                data = self.client.get(self.url, {"sort": sort}).json()
                self.assertEqual(data["sort"], sort)
                self.assertEqual([i["offer_id"] for i in data["items"]], [o.id for o in expected])

    def test_filters_change_count(self):
        data = self.client.get(self.url, {"delivery_max_days": "1"}).json()
        self.assertEqual((data["count"], len(data["items"])), (1, 1))

    def test_criterion_recalculates(self):
        data = self.client.get(self.url, {"criterion": "speed"}).json()
        self.assertEqual(data["criterion"], "speed")
        self.assertEqual(data["recommendation"]["offer_id"], self.o_fast.id)
        self.assertEqual(data["items"][0]["offer_id"], self.o_fast.id)

    def test_foreign_search_is_not_found(self):
        other = SearchRequest.objects.create(raw_query="x", session_key="other")
        self.assertEqual(self.client.get(reverse("search:results_api", args=[other.id])).status_code, 404)

    def test_anonymous_cannot_read_user_search(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_cyrillic_is_not_escaped(self):
        self.assertIn("Дешёвый", self.client.get(self.url).content.decode())

    def test_search_without_results(self):
        empty = SearchRequest.objects.create(user=self.user, raw_query="ничего", status="done")
        data = self.client.get(reverse("search:results_api", args=[empty.id])).json()
        self.assertEqual((data["count"], data["items"], data["recommendation"]), (0, [], None))
