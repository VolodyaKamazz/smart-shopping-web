from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Category, Offer, Product, Shop
from search.models import SearchRequest
from search.test_ranking import RankingBase

from .models import Favorite
from .owners import claim_session_favorites, fixed_price

PASSWORD = "Str0ng-pass-123"


class FavBase(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Смартфоны", slug="smartphones", keywords="смартфон")
        self.product = Product.objects.create(category=category, name="Samsung Galaxy A55")
        self.other = Product.objects.create(category=category, name="Xiaomi 14T")
        self.dns = Shop.objects.create(name="DNS")
        self.citi = Shop.objects.create(name="Ситилинк")
        self.o_dns = self.offer(self.product, self.dns, "31000", "d1")
        self.o_citi = self.offer(self.product, self.citi, "29500", "c1")
        self.o_other = self.offer(self.other, self.dns, "40000", "d2")
        self.toggle_url = reverse("favorites:toggle", args=[self.product.id])
        self.list_url = reverse("favorites:list")

    def offer(self, product, shop, price, external_id):
        return Offer.objects.create(product=product, shop=shop, external_id=external_id,
                                    url="https://shop.example/item", title_raw=f"{product.name} {shop.name}",
                                    price=Decimal(price))

    def add(self, client=None, product=None, **data):
        client = client or self.client
        product = product or self.product
        return client.post(reverse("favorites:toggle", args=[product.id]), data)

    def add_json(self, client=None, **data):
        client = client or self.client
        return client.post(self.toggle_url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def make_user(self, name="fan"):
        return User.objects.create_user(name, f"{name}@example.com", PASSWORD)


class AnonymousToggleTests(FavBase):
    def test_creates_favorite_bound_to_session(self):
        self.add()
        favorite = Favorite.objects.get()
        self.assertIsNone(favorite.user)
        self.assertEqual(favorite.session_token, self.client.session["favorites_token"])
        self.assertEqual(favorite.product, self.product)

    def test_toggle_twice_removes(self):
        self.add()
        self.add()
        self.assertEqual(Favorite.objects.count(), 0)

    def test_default_redirect_to_list(self):
        self.assertRedirects(self.add(), self.list_url)

    def test_safe_next_is_followed(self):
        response = self.add(next="/results/abc/")
        self.assertEqual(response["Location"], "/results/abc/")

    def test_external_next_is_ignored(self):
        for target in ("https://evil.example/", "//evil.example/path"):
            with self.subTest(target=target):
                self.assertEqual(self.add(next=target)["Location"], self.list_url)
                Favorite.objects.all().delete()

    def test_json_response(self):
        data = self.add_json().json()
        self.assertEqual(data, {"is_favorite": True, "product_id": self.product.id, "price_at_add": 29500.0,
                                "favorites_count": 1})
        data = self.add_json().json()
        self.assertEqual(data, {"is_favorite": False, "product_id": self.product.id, "price_at_add": None,
                                "favorites_count": 0})

    def test_json_by_accept_header(self):
        response = self.client.post(self.toggle_url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.json()["is_favorite"], True)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)

    def test_unknown_product(self):
        self.assertEqual(self.client.post(reverse("favorites:toggle", args=[999999])).status_code, 404)

    def test_csrf_is_required(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(self.toggle_url).status_code, 403)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_two_products_are_independent(self):
        self.add()
        self.add(product=self.other)
        self.assertEqual(Favorite.objects.count(), 2)
        self.add()
        self.assertEqual(list(Favorite.objects.values_list("product_id", flat=True)), [self.other.id])

    def test_session_token_is_stable(self):
        self.add()
        token = self.client.session["favorites_token"]
        self.add(product=self.other)
        self.assertEqual(self.client.session["favorites_token"], token)

    def test_no_session_is_created_by_viewing_list(self):
        self.client.get(self.list_url)
        self.assertNotIn("favorites_token", self.client.session)


class FixedPriceTests(FavBase):
    def test_lowest_active_price_is_fixed_by_default(self):
        self.add()
        self.assertEqual(Favorite.objects.get().price_at_add, Decimal("29500"))
        self.assertIsNone(Favorite.objects.get().offer)

    def test_price_of_chosen_offer_is_fixed(self):
        self.add(offer_id=str(self.o_dns.id))
        favorite = Favorite.objects.get()
        self.assertEqual((favorite.price_at_add, favorite.offer), (Decimal("31000"), self.o_dns))

    def test_offer_of_other_product_is_ignored(self):
        self.add(offer_id=str(self.o_other.id))
        favorite = Favorite.objects.get()
        self.assertEqual(favorite.price_at_add, Decimal("29500"))
        self.assertIsNone(favorite.offer)

    def test_garbage_offer_id_is_ignored(self):
        for value in ("abc", "999999", "", "-1", "1.5"):
            with self.subTest(value=value):
                self.add(offer_id=value)
                self.assertEqual(Favorite.objects.get().price_at_add, Decimal("29500"))
                Favorite.objects.all().delete()

    def test_inactive_and_out_of_stock_offers_are_skipped(self):
        Offer.objects.filter(pk=self.o_citi.pk).update(is_active=False)
        self.add()
        self.assertEqual(Favorite.objects.get().price_at_add, Decimal("31000"))
        Favorite.objects.all().delete()
        Offer.objects.filter(pk=self.o_dns.pk).update(in_stock=False)
        self.add()
        self.assertIsNone(Favorite.objects.get().price_at_add)

    def test_inactive_chosen_offer_falls_back_to_lowest(self):
        Offer.objects.filter(pk=self.o_dns.pk).update(is_active=False)
        self.add(offer_id=str(self.o_dns.id))
        favorite = Favorite.objects.get()
        self.assertEqual(favorite.price_at_add, Decimal("29500"))
        self.assertIsNone(favorite.offer)

    def test_product_without_offers(self):
        lonely = Product.objects.create(category=self.product.category, name="Без предложений")
        self.add(product=lonely)
        self.assertIsNone(Favorite.objects.get().price_at_add)

    def test_price_stays_fixed_after_offer_changes(self):
        self.add()
        Offer.objects.filter(pk=self.o_citi.pk).update(price=Decimal("20000"))
        self.assertEqual(Favorite.objects.get().price_at_add, Decimal("29500"))
        self.client.get(self.list_url)
        self.assertEqual(Favorite.objects.get().price_at_add, Decimal("29500"))

    def test_readding_fixes_new_price(self):
        self.add()
        self.add()
        Offer.objects.filter(pk=self.o_citi.pk).update(price=Decimal("28000"))
        self.add()
        self.assertEqual(Favorite.objects.get().price_at_add, Decimal("28000"))

    def test_fixed_price_helper(self):
        self.assertEqual(fixed_price(self.product), Decimal("29500"))
        self.assertEqual(fixed_price(self.product, self.o_dns), Decimal("31000"))
        self.assertEqual(fixed_price(self.product, self.o_other), Decimal("29500"))


class ListPageTests(FavBase):
    def rows(self, client=None):
        return (client or self.client).get(self.list_url).context["rows"]

    def test_empty_page(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "В избранном пока ничего нет")

    def test_anonymous_hint(self):
        self.add()
        self.assertContains(self.client.get(self.list_url), "хранится в вашей сессии")

    def test_no_hint_on_empty_page(self):
        self.assertNotContains(self.client.get(self.list_url), "хранится в вашей сессии")

    def test_row_contains_fixed_and_current_price(self):
        self.add()
        row = self.rows()[0]
        self.assertEqual(row["product"], self.product)
        self.assertEqual(row["fixed"], "29\u00a0500 ₽")
        self.assertEqual(row["current"], "29\u00a0500 ₽")
        self.assertEqual((row["trend"], row["diff"]), ("same", ""))

    def test_price_drop(self):
        self.add()
        Offer.objects.filter(pk=self.o_citi.pk).update(price=Decimal("28000"))
        row = self.rows()[0]
        self.assertEqual((row["fixed"], row["current"]), ("29\u00a0500 ₽", "28\u00a0000 ₽"))
        self.assertEqual((row["trend"], row["diff"]), ("down", "−1\u00a0500 ₽"))

    def test_price_rise(self):
        self.add()
        Offer.objects.filter(pk=self.o_citi.pk).update(price=Decimal("30000"))
        row = self.rows()[0]
        self.assertEqual((row["trend"], row["diff"]), ("up", "+500 ₽"))

    def test_row_follows_chosen_offer(self):
        self.add(offer_id=str(self.o_dns.id))
        Offer.objects.filter(pk=self.o_dns.pk).update(price=Decimal("30000"))
        row = self.rows()[0]
        self.assertEqual((row["shop"], row["fixed"], row["current"]), ("DNS", "31\u00a0000 ₽", "30\u00a0000 ₽"))

    def test_chosen_offer_became_inactive_falls_back_to_lowest(self):
        self.add(offer_id=str(self.o_dns.id))
        Offer.objects.filter(pk=self.o_dns.pk).update(is_active=False)
        self.assertEqual(self.rows()[0]["current"], "29\u00a0500 ₽")

    def test_unavailable_product(self):
        self.add()
        Offer.objects.filter(product=self.product).update(is_active=False)
        row = self.rows()[0]
        self.assertEqual((row["current"], row["trend"]), ("нет в наличии", None))

    def test_without_fixed_price(self):
        Offer.objects.filter(product=self.product).update(in_stock=False)
        self.add()
        row = self.rows()[0]
        self.assertEqual((row["fixed"], row["trend"]), ("—", None))

    def test_newest_first(self):
        self.add()
        self.add(product=self.other)
        self.assertEqual([r["product"] for r in self.rows()], [self.other, self.product])

    def test_sessions_are_isolated(self):
        self.add()
        other_client = Client()
        self.assertEqual(self.rows(other_client), [])
        self.assertEqual(len(self.rows()), 1)

    def test_remove_button_form_is_rendered(self):
        self.add()
        self.assertContains(self.client.get(self.list_url), f'action="{self.toggle_url}"')

    def test_header_link_for_anonymous(self):
        self.assertContains(self.client.get("/"), f'href="{self.list_url}"')

    def test_header_link_for_user(self):
        self.client.force_login(self.make_user())
        self.assertContains(self.client.get("/"), f'href="{self.list_url}"')

    def test_notifications_link_only_for_users(self):
        self.assertNotContains(self.client.get(self.list_url), "Уведомления о снижении цены")
        self.client.force_login(self.make_user())
        self.assertContains(self.client.get(self.list_url), "Уведомления о снижении цены")


class ModelConstraintTests(FavBase):
    def test_same_session_cannot_duplicate_product(self):
        Favorite.objects.create(session_token="a" * 32, product=self.product)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(session_token="a" * 32, product=self.product)

    def test_different_sessions_may_share_product(self):
        Favorite.objects.create(session_token="a" * 32, product=self.product)
        Favorite.objects.create(session_token="b" * 32, product=self.product)
        self.assertEqual(Favorite.objects.count(), 2)

    def test_user_cannot_duplicate_product(self):
        user = self.make_user()
        Favorite.objects.create(user=user, product=self.product)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(user=user, product=self.product)

    def test_owner_is_required(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Favorite.objects.create(product=self.product)


class LoggedInTests(FavBase):
    def test_user_favorite_has_no_token(self):
        user = self.make_user()
        self.client.force_login(user)
        self.add()
        favorite = Favorite.objects.get()
        self.assertEqual((favorite.user, favorite.session_token), (user, ""))
        self.assertEqual(favorite.price_at_add, Decimal("29500"))

    def test_user_does_not_see_foreign_favorites(self):
        Favorite.objects.create(user=self.make_user("other"), product=self.product)
        self.client.force_login(self.make_user())
        self.assertEqual(self.client.get(self.list_url).context["rows"], [])

    def test_user_does_not_see_session_favorites_of_others(self):
        Favorite.objects.create(session_token="a" * 32, product=self.product)
        self.client.force_login(self.make_user())
        self.assertEqual(self.client.get(self.list_url).context["rows"], [])

    def test_cabinet_still_lists_favorites(self):
        user = self.make_user()
        Favorite.objects.create(user=user, product=self.product)
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("accounts:cabinet")), self.product.name)


class SessionToAccountTests(FavBase):
    def log_in(self, user):
        return self.client.post(reverse("accounts:login"), {"username": user.username, "password": PASSWORD})

    def test_login_moves_session_favorites_to_user(self):
        user = self.make_user()
        self.add()
        self.add(product=self.other)
        self.log_in(user)
        self.assertEqual(Favorite.objects.filter(user=user).count(), 2)
        self.assertEqual(Favorite.objects.filter(user__isnull=True).count(), 0)
        self.assertEqual(Favorite.objects.filter(session_token__gt="").count(), 0)

    def test_fixed_price_survives_login(self):
        user = self.make_user()
        self.add()
        Offer.objects.filter(pk=self.o_citi.pk).update(price=Decimal("25000"))
        self.log_in(user)
        self.assertEqual(Favorite.objects.get(user=user).price_at_add, Decimal("29500"))

    def test_existing_user_favorite_wins_on_duplicate(self):
        user = self.make_user()
        mine = Favorite.objects.create(user=user, product=self.product, price_at_add=Decimal("10"))
        self.add()
        self.log_in(user)
        self.assertEqual(Favorite.objects.count(), 1)
        self.assertEqual(Favorite.objects.get().pk, mine.pk)

    def test_token_is_removed_after_login(self):
        self.add()
        self.log_in(self.make_user())
        self.assertNotIn("favorites_token", self.client.session)

    def test_registration_moves_session_favorites(self):
        self.add()
        response = self.client.post(reverse("accounts:register"), {
            "username": "newbie", "email": "newbie@example.com", "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Favorite.objects.get().user.username, "newbie")

    def test_favorites_after_login_are_listed(self):
        user = self.make_user()
        self.add()
        self.log_in(user)
        self.assertEqual(len(self.client.get(self.list_url).context["rows"]), 1)

    def test_logout_gives_clean_anonymous_session(self):
        user = self.make_user()
        self.add()
        self.log_in(user)
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(self.list_url).context["rows"], [])
        self.assertEqual(Favorite.objects.filter(user=user).count(), 1)

    def test_other_session_is_untouched_by_login(self):
        stranger = Client()
        self.add(stranger)
        self.add()
        self.log_in(self.make_user())
        self.assertEqual(Favorite.objects.filter(user__isnull=True).count(), 1)
        self.assertEqual(len(stranger.get(self.list_url).context["rows"]), 1)

    def test_login_without_favorites(self):
        response = self.log_in(self.make_user())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_wrong_password_keeps_session_favorites(self):
        self.add()
        self.client.post(reverse("accounts:login"), {"username": "fan", "password": "wrong"})
        self.assertEqual(Favorite.objects.filter(user__isnull=True).count(), 1)

    def test_claim_without_token(self):
        class Req:
            session = {}
        self.assertEqual(claim_session_favorites(Req(), self.make_user()), 0)


class ResultsFlagTests(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)

    def api_items(self):
        data = self.client.get(f"/results/{self.search.id}/api/").json()
        return {i["offer_id"]: i for i in data["items"]}

    def test_flags_default_to_false(self):
        self.assertFalse(any(i["is_favorite"] for i in self.api_items().values()))

    def test_product_id_is_exposed(self):
        self.assertEqual(self.api_items()[self.o_fast.id]["product_id"], self.product.id)

    def test_flag_after_adding(self):
        self.client.post(f"/favorites/{self.product.id}/toggle/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(all(i["is_favorite"] for i in self.api_items().values()))

    def test_flag_in_html_context(self):
        self.client.post(f"/favorites/{self.product.id}/toggle/")
        items = self.client.get(f"/results/{self.search.id}/").context["items"]
        self.assertTrue(all(i["is_favorite"] for i in items))

    def test_flag_for_anonymous_session(self):
        anonymous = Client()
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=list(self.offers)):
            anonymous.post("/search/", {"query": "смартфон"})
        search = SearchRequest.objects.get(user__isnull=True)
        url = f"/results/{search.id}/api/"
        self.assertFalse(any(i["is_favorite"] for i in anonymous.get(url).json()["items"]))
        anonymous.post(f"/favorites/{self.product.id}/toggle/")
        self.assertTrue(all(i["is_favorite"] for i in anonymous.get(url).json()["items"]))

    def test_flag_does_not_leak_to_other_session(self):
        Client().post(f"/favorites/{self.product.id}/toggle/")
        self.assertFalse(any(i["is_favorite"] for i in self.api_items().values()))
