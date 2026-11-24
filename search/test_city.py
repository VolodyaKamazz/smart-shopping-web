from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse

from accounts.models import User
from delivery.models import City, ShopDeliveryRule

from .city import SESSION_KEY, current_city
from .models import SearchRequest
from .test_ranking import RankingBase

CITY_URL = "/city/"


class CityBase(RankingBase):
    def setUp(self):
        super().setUp()
        self.moscow = City.objects.create(name="Москва", zone=1)
        self.abakan = City.objects.create(name="Абакан", zone=3)

    def guest_search(self, client, city=None):
        data = {"query": "смартфон"}
        if city is not None:
            data["city"] = str(city.pk)
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            client.post("/search/", data)
        return SearchRequest.objects.filter(user__isnull=True).order_by("-created_at").first()

    def set_city(self, client, city, **extra):
        value = city.pk if hasattr(city, "pk") else city
        return client.post(CITY_URL, {"city": value}, **extra)

    def api(self, client, search, **params):
        return client.get(f"/results/{search.id}/api/", params).json()


class CityListTests(CityBase):
    def test_guest_gets_all_cities_sorted_by_name(self):
        response = self.client.get("/")
        names = [c.name for c in response.context["cities"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(set(names), {"Екатеринбург", "Москва", "Абакан"})

    def test_cities_are_rendered_in_header_for_guest(self):
        html = self.client.get("/").content.decode()
        self.assertIn('name="city"', html)
        for city in (self.city, self.moscow, self.abakan):
            self.assertIn(f'<option value="{city.pk}"', html)
        self.assertIn(f'action="{CITY_URL}"', html)

    def test_no_city_selected_by_default(self):
        response = self.client.get("/")
        self.assertFalse(response.context["current_city"])
        self.assertNotIn(" selected", response.content.decode().split('name="city"')[1].split("</select>")[0])

    def test_selected_city_is_marked(self):
        self.set_city(self.client, self.moscow)
        html = self.client.get("/").content.decode()
        self.assertIn(f'<option value="{self.moscow.pk}" selected>', html)

    def test_user_city_is_marked(self):
        self.client.force_login(self.user)
        html = self.client.get("/").content.decode()
        self.assertIn(f'<option value="{self.city.pk}" selected>', html)

    def test_header_next_points_to_current_page(self):
        html = self.client.get("/favorites/").content.decode()
        self.assertIn('name="next" value="/favorites/"', html)

    def test_cities_are_not_queried_for_pages_without_header_use(self):
        from django.http import HttpRequest
        from .context_processors import location
        request = HttpRequest()
        request.session = {}
        request.user = AnonymousUser()
        with self.assertNumQueries(0):
            location(request)


class SetCityTests(CityBase):
    def test_guest_choice_is_stored_in_session(self):
        self.set_city(self.client, self.moscow)
        self.assertEqual(self.client.session[SESSION_KEY], self.moscow.pk)

    def test_default_redirect_is_home(self):
        self.assertRedirects(self.set_city(self.client, self.moscow), reverse("search:home"))

    def test_safe_next_is_followed(self):
        response = self.client.post(CITY_URL, {"city": self.moscow.pk, "next": "/favorites/"})
        self.assertEqual(response["Location"], "/favorites/")

    def test_external_next_is_ignored(self):
        for target in ("https://evil.example/", "//evil.example/x"):
            with self.subTest(target=target):
                response = self.client.post(CITY_URL, {"city": self.moscow.pk, "next": target})
                self.assertEqual(response["Location"], reverse("search:home"))

    def test_unknown_city_is_rejected_with_message(self):
        for value in ("999999", "abc", "²", "-1", "1.5"):
            with self.subTest(value=value):
                client = Client()
                response = self.set_city(client, value)
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(SESSION_KEY, client.session)

    def test_unknown_city_json_is_400(self):
        response = self.set_city(self.client, "999999", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual((response.status_code, response.json()), (400, {"error": "unknown_city"}))

    def test_json_response_contains_city(self):
        response = self.set_city(self.client, self.moscow, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json(), {"city": {"id": self.moscow.pk, "name": "Москва"}})

    def test_empty_value_clears_guest_city(self):
        self.set_city(self.client, self.moscow)
        response = self.set_city(self.client, "", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json(), {"city": None})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_user_choice_goes_to_profile(self):
        self.client.force_login(self.user)
        self.set_city(self.client, self.moscow)
        self.user.refresh_from_db()
        self.assertEqual(self.user.city, self.moscow)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_user_can_clear_city(self):
        self.client.force_login(self.user)
        self.set_city(self.client, "")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.city)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(CITY_URL).status_code, 405)

    def test_csrf_is_required(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(CITY_URL, {"city": self.moscow.pk}).status_code, 403)

    def test_sessions_are_isolated(self):
        self.set_city(self.client, self.moscow)
        other = Client()
        self.assertNotIn(SESSION_KEY, other.session)

    def test_deleted_city_in_session_is_ignored(self):
        self.set_city(self.client, self.abakan)
        self.abakan.delete()
        response = self.client.get("/")
        self.assertFalse(response.context["current_city"])


class GuestSearchCityTests(CityBase):
    def test_guest_search_without_city_has_unknown_delivery(self):
        search = self.guest_search(self.client)
        self.assertIsNone(search.city)
        self.assertTrue(all(r.delivery_price is None for r in search.results.all()))
        data = self.api(self.client, search)
        self.assertIsNone(data["city"])
        self.assertTrue(all(i["delivery_price"] is None for i in data["items"]))

    def test_search_uses_session_city(self):
        self.set_city(self.client, self.city)
        search = self.guest_search(self.client)
        self.assertEqual(search.city, self.city)
        fast = search.results.get(offer=self.o_fast)
        self.assertEqual((fast.delivery_price, fast.delivery_min_days, fast.delivery_max_days), (0, 1, 1))

    def test_post_city_beats_session_city(self):
        self.set_city(self.client, self.moscow)
        search = self.guest_search(self.client, city=self.city)
        self.assertEqual(search.city, self.city)

    def test_garbage_post_city_does_not_break_search(self):
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            response = self.client.post("/search/", {"query": "смартфон", "city": "²"})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(SearchRequest.objects.get().city)

    def test_user_search_uses_profile_city(self):
        self.client.force_login(self.user)
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            self.client.post("/search/", {"query": "смартфон"})
        self.assertEqual(SearchRequest.objects.get().city, self.city)


class ResultsFollowCityTests(CityBase):
    def setUp(self):
        super().setUp()
        self.search = self.guest_search(self.client)

    def test_choosing_city_updates_delivery_on_results(self):
        self.set_city(self.client, self.city)
        data = self.api(self.client, self.search)
        items = {i["offer_id"]: i for i in data["items"]}
        self.assertEqual(data["city"], {"id": self.city.pk, "name": "Екатеринбург"})
        self.assertEqual((items[self.o_fast.id]["delivery_price"], items[self.o_fast.id]["delivery_max_days"]), (0.0, 1))
        self.assertEqual((items[self.o_cheap.id]["delivery_price"], items[self.o_cheap.id]["total_price"]), (300.0, 27300.0))
        self.assertIsNone(items[self.o_plain.id]["delivery_price"])

    def test_city_is_saved_in_search(self):
        self.set_city(self.client, self.city)
        self.api(self.client, self.search)
        self.search.refresh_from_db()
        self.assertEqual(self.search.city, self.city)

    def test_html_page_follows_city_too(self):
        self.set_city(self.client, self.city)
        response = self.client.get(f"/results/{self.search.id}/")
        item = next(i for i in response.context["items"] if i["offer_id"] == self.o_cheap.id)
        self.assertIn("300", item["delivery"])

    def test_recommendation_is_recomputed(self):
        before = self.api(self.client, self.search)["recommendation"]["explanation"]
        self.set_city(self.client, self.city)
        after = self.api(self.client, self.search)["recommendation"]["explanation"]
        self.assertIn("стоимость доставки уточняется", before.replace("уточняется", "уточняется"))
        self.assertNotEqual(before, after)

    def test_results_stay_complete(self):
        self.set_city(self.client, self.city)
        data = self.api(self.client, self.search)
        self.assertEqual(data["count"], 3)
        self.assertEqual(sum(1 for i in data["items"] if i["is_recommended"]), 1)
        self.assertEqual(self.search.results.count(), 3)

    def test_chosen_criterion_survives_city_change(self):
        self.client.get(f"/results/{self.search.id}/api/", {"criterion": "speed"})
        self.set_city(self.client, self.city)
        data = self.api(self.client, self.search)
        self.assertEqual(data["criterion"], "speed")
        self.assertEqual(data["recommendation"]["offer_id"], self.o_fast.id)

    def test_same_city_is_not_recalculated(self):
        self.set_city(self.client, self.city)
        self.api(self.client, self.search)
        with patch("search.ranking.change_city") as mocked:
            self.api(self.client, self.search)
        mocked.assert_not_called()

    def test_city_specific_rule_is_used(self):
        ShopDeliveryRule.objects.create(shop=self.cheap, city=self.moscow, cost=100, min_days=2, max_days=2)
        self.set_city(self.client, self.moscow)
        items = {i["offer_id"]: i for i in self.api(self.client, self.search)["items"]}
        self.assertEqual((items[self.o_cheap.id]["delivery_price"], items[self.o_cheap.id]["delivery_max_days"]), (100.0, 2))

    def test_switching_between_cities_recalculates_each_time(self):
        ShopDeliveryRule.objects.create(shop=self.cheap, city=self.moscow, cost=100, min_days=2, max_days=2)
        for city, expected in ((self.moscow, 100.0), (self.city, 300.0), (self.moscow, 100.0)):
            self.set_city(self.client, city)
            items = {i["offer_id"]: i for i in self.api(self.client, self.search)["items"]}
            self.assertEqual(items[self.o_cheap.id]["delivery_price"], expected)

    def test_clearing_city_keeps_results_as_they_were(self):
        self.set_city(self.client, self.city)
        self.api(self.client, self.search)
        self.set_city(self.client, "")
        data = self.api(self.client, self.search)
        self.assertEqual(data["city"]["id"], self.city.pk)

    def test_other_session_is_not_affected(self):
        stranger = Client()
        self.set_city(stranger, self.moscow)
        data = self.api(self.client, self.search)
        self.assertIsNone(data["city"])

    def test_running_search_is_not_touched(self):
        self.search.status = "running"
        self.search.save(update_fields=["status"])
        self.set_city(self.client, self.city)
        with patch("search.ranking.change_city") as mocked:
            self.client.get(f"/results/{self.search.id}/api/")
        mocked.assert_not_called()

    def test_user_profile_city_change_updates_results(self):
        self.client.force_login(self.user)
        search = self.run_for(city=None)
        self.set_city(self.client, self.moscow)
        ShopDeliveryRule.objects.create(shop=self.cheap, city=self.moscow, cost=50, min_days=1, max_days=1)
        items = {i["offer_id"]: i for i in self.api(self.client, search)["items"]}
        self.assertEqual(items[self.o_cheap.id]["delivery_price"], 50.0)

    def test_budget_exclusions_are_kept(self):
        from . import ranking
        self.set_priority("price", Decimal("27500"))
        search = self.run_for()
        self.assertEqual(search.facts["excluded_over_budget"], 2)
        ranking.change_city(search, self.moscow)
        search.refresh_from_db()
        self.assertEqual(search.facts["excluded_over_budget"], 2)
        self.assertEqual(list(search.results.values_list("offer_id", flat=True)), [self.o_cheap.id])

    def test_change_city_with_empty_results(self):
        from . import ranking
        empty = SearchRequest.objects.create(user=self.user, raw_query="x", status="done", city=self.city)
        ranking.change_city(empty, self.moscow)
        empty.refresh_from_db()
        self.assertEqual(empty.city, self.moscow)
        self.assertIsNone(empty.recommended_offer)


class LoginKeepsCityTests(CityBase):
    PASSWORD = "Str0ng-pass-123"

    def log_in(self, client, user):
        return client.post(reverse("accounts:login"), {"username": user.username, "password": self.PASSWORD})

    def test_guest_city_moves_to_user_without_city(self):
        user = User.objects.create_user("nocity", "nocity@example.com", self.PASSWORD)
        self.set_city(self.client, self.moscow)
        self.log_in(self.client, user)
        user.refresh_from_db()
        self.assertEqual(user.city, self.moscow)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_user_own_city_wins(self):
        self.user.set_password(self.PASSWORD)
        self.user.save()
        self.set_city(self.client, self.moscow)
        self.log_in(self.client, self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.city, self.city)

    def test_login_without_guest_city(self):
        user = User.objects.create_user("plain", "plain@example.com", self.PASSWORD)
        self.assertEqual(self.log_in(self.client, user).status_code, 302)
        user.refresh_from_db()
        self.assertIsNone(user.city)

    def test_current_city_helper(self):
        from django.http import HttpRequest
        request = HttpRequest()
        request.session = {SESSION_KEY: self.abakan.pk}
        request.user = AnonymousUser()
        self.assertEqual(current_city(request), self.abakan)
