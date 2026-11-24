from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.test import Client
from django.urls import reverse

from catalog.models import Offer, Product, Shop
from delivery.models import City, ShopDeliveryRule
from delivery.services import DeliveryInfo
from search.images import image_of
from search.test_ranking import RankingBase

from .context_processors import favorites as favorites_processor
from .test_favorites import FavBase


class FavoritesCountTests(FavBase):
    def count_in_header(self, client=None):
        html = (client or self.client).get("/").content.decode()
        return html.split("data-fav-count>")[1].split("</span>")[0].strip()

    def test_header_has_counter_element(self):
        self.assertIn("data-fav-count", self.client.get("/").content.decode())

    def test_empty_counter_shows_title(self):
        self.assertEqual(self.count_in_header(), "Избранное")

    def test_counter_follows_additions_and_removals(self):
        self.add()
        self.assertEqual(self.count_in_header(), "(1)")
        self.add(product=self.other)
        self.assertEqual(self.count_in_header(), "(2)")
        self.add()
        self.assertEqual(self.count_in_header(), "(1)")
        self.add(product=self.other)
        self.assertEqual(self.count_in_header(), "Избранное")

    def test_context_value(self):
        self.add()
        self.assertEqual(int(str(self.client.get("/").context["favorites_count"])), 1)

    def test_counter_is_per_session(self):
        self.add()
        self.assertEqual(self.count_in_header(Client()), "Избранное")

    def test_counter_for_logged_in_user_counts_only_own(self):
        user = self.make_user()
        self.add(self.client)
        other_user = self.make_user("other")
        from .models import Favorite
        Favorite.objects.create(user=other_user, product=self.product)
        Favorite.objects.create(user=user, product=self.product)
        Favorite.objects.create(user=user, product=self.other)
        self.client.force_login(user)
        self.assertEqual(self.count_in_header(), "(2)")

    def test_counter_after_login_includes_moved_favorites(self):
        user = self.make_user()
        self.add()
        self.client.post(reverse("accounts:login"), {"username": user.username, "password": "Str0ng-pass-123"})
        self.assertEqual(self.count_in_header(), "(1)")

    def test_processor_makes_no_queries_for_fresh_guest(self):
        request = HttpRequest()
        request.session = {}
        request.user = AnonymousUser()
        with self.assertNumQueries(0):
            self.assertEqual(int(str(favorites_processor(request)["favorites_count"])), 0)

    def test_counter_is_shown_on_every_page(self):
        self.add()
        for url in ("/", self.list_url, reverse("accounts:login"), reverse("accounts:register")):
            with self.subTest(url=url):
                self.assertIn("(1)", self.client.get(url).content.decode().split("data-fav-count>")[1][:20])


class FavoriteDeliveryTests(FavBase):
    def setUp(self):
        super().setUp()
        self.city = City.objects.create(name="Екатеринбург", zone=1)
        ShopDeliveryRule.objects.create(shop=self.dns, city=None, cost=500, min_days=2, max_days=3)
        ShopDeliveryRule.objects.create(shop=self.citi, city=None, cost=400, free_from=Decimal("29000"),
                                        min_days=1, max_days=1)

    def choose_city(self, client=None):
        (client or self.client).post("/city/", {"city": self.city.pk})

    def row(self, client=None):
        return (client or self.client).get(self.list_url).context["rows"][0]

    def test_delivery_of_lowest_offer(self):
        self.choose_city()
        self.add()
        row = self.row()
        self.assertEqual(row["shop"], "Ситилинк")
        self.assertEqual(row["delivery"], "бесплатно, 1 дн.")
        self.assertEqual(row["total"], "29\u00a0500 ₽")

    def test_delivery_of_chosen_offer(self):
        self.choose_city()
        self.add(offer_id=str(self.o_dns.id))
        row = self.row()
        self.assertEqual(row["shop"], "DNS")
        self.assertEqual(row["delivery"], "500 ₽, 2–3 дн.")
        self.assertEqual(row["total"], "31\u00a0500 ₽")

    def test_without_city_asks_to_choose_one(self):
        self.add()
        row = self.row()
        self.assertEqual(row["delivery"], "выберите город, чтобы увидеть доставку")
        self.assertEqual(row["total"], "")

    def test_shop_without_rules_has_unknown_delivery(self):
        ShopDeliveryRule.objects.filter(shop=self.citi).delete()
        self.choose_city()
        self.add()
        row = self.row()
        self.assertEqual((row["delivery"], row["total"]), ("уточняется", ""))

    def test_unavailable_chosen_offer_falls_back_to_cheapest(self):
        self.choose_city()
        self.add(offer_id=str(self.o_dns.id))
        Offer.objects.filter(pk=self.o_dns.pk).update(is_active=False)
        row = self.row()
        self.assertEqual((row["shop"], row["delivery"]), ("Ситилинк", "бесплатно, 1 дн."))

    def test_nothing_available_shows_no_delivery(self):
        self.choose_city()
        self.add()
        Offer.objects.filter(product=self.product).update(in_stock=False)
        row = self.row()
        self.assertEqual((row["shop"], row["delivery"], row["total"], row["current"]), ("", "", "", "нет в наличии"))

    def test_real_delivery_calculation_has_priority(self):
        self.choose_city()
        self.add()
        info = DeliveryInfo(price=Decimal("700"), min_days=2, max_days=3, source="cdek")
        with patch("delivery.services.calc_delivery", return_value=info):
            row = self.row()
        self.assertEqual((row["delivery"], row["total"]), ("700 ₽, 2–3 дн.", "30\u00a0200 ₽"))

    def test_calculation_error_is_isolated(self):
        self.choose_city()
        self.add()
        with patch("delivery.services.calc_delivery", side_effect=RuntimeError("boom")), \
                self.assertLogs("search.ranking", level="ERROR"):
            response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"][0]["delivery"], "уточняется")

    def test_same_days_are_shown_once(self):
        ShopDeliveryRule.objects.filter(shop=self.dns).update(min_days=3, max_days=3)
        self.choose_city()
        self.add(offer_id=str(self.o_dns.id))
        self.assertEqual(self.row()["delivery"], "500 ₽, 3 дн.")

    def test_page_shows_delivery_and_total(self):
        self.choose_city()
        self.add()
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("Доставка: бесплатно, 1 дн.", html)
        self.assertIn("Итого с доставкой: 29\u00a0500 ₽", html)

    def test_logged_in_user_uses_profile_city(self):
        user = self.make_user()
        user.city = self.city
        user.save()
        self.client.force_login(user)
        self.add()
        self.assertEqual(self.row()["delivery"], "бесплатно, 1 дн.")

    def test_each_favorite_gets_its_own_delivery(self):
        ShopDeliveryRule.objects.create(shop=self.dns, city=self.city, cost=250, min_days=1, max_days=2)
        self.choose_city()
        self.add()
        self.add(product=self.other)
        rows = {r["product"].name: r for r in self.client.get(self.list_url).context["rows"]}
        self.assertEqual(rows[self.product.name]["delivery"], "бесплатно, 1 дн.")
        self.assertEqual(rows[self.other.name]["delivery"], "250 ₽, 1–2 дн.")
        self.assertEqual(rows[self.other.name]["total"], "40\u00a0250 ₽")


class ImageUrlTests(RankingBase):
    def setUp(self):
        super().setUp()
        self.search = self.run_for()
        self.client.force_login(self.user)
        self.api_url = f"/results/{self.search.id}/api/"

    def images(self):
        return {i["offer_id"]: i["image_url"] for i in self.client.get(self.api_url).json()["items"]}

    def set_image(self, url):
        Product.objects.filter(pk=self.product.pk).update(image_url=url)

    def test_empty_by_default(self):
        self.assertEqual(set(self.images().values()), {""})

    def test_url_is_passed_to_api(self):
        self.set_image("https://img.example/a55.jpg")
        self.assertEqual(set(self.images().values()), {"https://img.example/a55.jpg"})

    def test_http_and_uppercase_scheme_are_accepted(self):
        for url in ("http://img.example/a.jpg", "HTTPS://img.example/a.jpg"):
            with self.subTest(url=url):
                self.set_image(url)
                self.assertEqual(set(self.images().values()), {url})

    def test_dangerous_schemes_are_dropped(self):
        for url in ("javascript:alert(1)", "data:image/png;base64,AAAA", "ftp://x/a.jpg", "//img.example/a.jpg", "a.jpg"):
            with self.subTest(url=url):
                self.set_image(url)
                self.assertEqual(set(self.images().values()), {""})

    def test_whitespace_is_trimmed(self):
        self.set_image("  https://img.example/a.jpg  ")
        self.assertEqual(set(self.images().values()), {"https://img.example/a.jpg"})

    def test_html_context_has_image(self):
        self.set_image("https://img.example/a.jpg")
        items = self.client.get(f"/results/{self.search.id}/").context["items"]
        self.assertTrue(all(i["image_url"] == "https://img.example/a.jpg" for i in items))

    def test_offer_without_product_has_no_image(self):
        orphan = Offer.objects.create(product=None, shop=self.fast, external_id="orphan", url="https://shop.example/o",
                                      title_raw="Без товара", price=Decimal("1000"))
        self.offers.append(orphan)
        search = self.run_for()
        data = self.client.get(f"/results/{search.id}/api/").json()
        item = next(i for i in data["items"] if i["offer_id"] == orphan.id)
        self.assertEqual(item["image_url"], "")

    def test_favorites_page_shows_picture(self):
        self.set_image("https://img.example/a.jpg")
        self.client.post(f"/favorites/{self.product.id}/toggle/")
        response = self.client.get(reverse("favorites:list"))
        self.assertEqual(response.context["rows"][0]["image_url"], "https://img.example/a.jpg")
        self.assertContains(response, '<img src="https://img.example/a.jpg"')

    def test_favorites_page_without_picture_uses_placeholder(self):
        self.client.post(f"/favorites/{self.product.id}/toggle/")
        response = self.client.get(reverse("favorites:list"))
        self.assertNotContains(response, "<img src=")
        self.assertContains(response, "🖼")

    def test_image_url_is_escaped_in_page(self):
        self.set_image('https://img.example/a.jpg?x="><script>alert(1)</script>')
        self.client.post(f"/favorites/{self.product.id}/toggle/")
        self.assertNotContains(self.client.get(reverse("favorites:list")), "<script>alert(1)</script>")

    def test_image_of_helper(self):
        self.assertEqual(image_of(None), "")
        self.assertEqual(image_of(self.product), "")
        self.set_image("https://img.example/a.jpg")
        self.product.refresh_from_db()
        self.assertEqual(image_of(self.product), "https://img.example/a.jpg")


class DigitRegressionTests(RankingBase):
    def test_superscript_digits_do_not_break_shop_filter(self):
        search = self.run_for()
        self.client.force_login(self.user)
        response = self.client.get(f"/results/{search.id}/api/", {"shop": "²"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    def test_superscript_offer_id_is_ignored(self):
        category = self.product.category
        product = Product.objects.create(category=category, name="Тест")
        response = self.client.post(f"/favorites/{product.id}/toggle/", {"offer_id": "²"})
        self.assertEqual(response.status_code, 302)
