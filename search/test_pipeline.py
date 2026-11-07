from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from catalog.models import Brand, Category, Offer, Product, Shop

from .models import SearchRequest, SearchResult
from .tasks import run_search


class PipelineBase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Смартфоны", slug="smartphones", keywords="смартфон, смартфоны, телефон")
        self.brand = Brand.objects.create(name="Samsung", normalized_name="samsung")
        self.shop = Shop.objects.create(name="Тестовый магазин")
        self.product = Product.objects.create(category=self.category, brand=self.brand, name="Samsung Galaxy A55")

    def make_offer(self, external_id, price):
        return Offer.objects.create(
            product=self.product, shop=self.shop, external_id=external_id,
            url=f"https://shop.example/{external_id}", title_raw=f"Offer {external_id}", price=Decimal(price))

    def make_search(self, query="смартфон Samsung до 50000"):
        return SearchRequest.objects.create(raw_query=query, session_key="s")


class ParsedQueryTests(PipelineBase):
    def test_parsed_is_saved_through_http_flow(self):
        self.client.post(reverse("search:start"), {"query": "смартфон Samsung до 50 000 рублей"})
        search = SearchRequest.objects.get()
        self.assertEqual(search.parsed, {
            "category": "smartphones", "brand": "samsung",
            "price_min": None, "price_max": 50000, "keywords": [],
        })
        self.assertEqual(search.status, "done")

    def test_without_catalog_services_search_still_finishes(self):
        search = self.make_search()
        run_search(str(search.id))
        search.refresh_from_db()
        self.assertEqual(search.status, "done")
        self.assertEqual(search.step, "")
        self.assertIsNotNone(search.finished_at)
        self.assertEqual(search.results.count(), 0)

    def test_search_products_gets_parsed_query(self):
        search = self.make_search()
        with patch("catalog.services.search_products", return_value=[]) as mocked:
            run_search(str(search.id))
        mocked.assert_called_once_with({
            "category": "smartphones", "brand": "samsung",
            "price_min": None, "price_max": 50000, "keywords": [],
        })

    def test_get_offers_gets_product_ids(self):
        search = self.make_search()
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=[]) as mocked:
            run_search(str(search.id))
        mocked.assert_called_once_with([self.product.pk])

    def test_product_ids_are_accepted_too(self):
        search = self.make_search()
        with patch("catalog.services.search_products", return_value=[self.product.pk]), \
                patch("catalog.services.get_offers", return_value=[]) as mocked:
            run_search(str(search.id))
        mocked.assert_called_once_with([self.product.pk])

    def test_get_offers_not_called_without_products(self):
        search = self.make_search()
        with patch("catalog.services.search_products", return_value=[]), \
                patch("catalog.services.get_offers") as mocked:
            run_search(str(search.id))
        mocked.assert_not_called()


class SearchResultTests(PipelineBase):
    def run_with_offers(self, search, offers):
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=offers):
            run_search(str(search.id))

    def test_results_are_saved_sorted_by_price(self):
        offers = [self.make_offer("a", "30000"), self.make_offer("b", "10000"), self.make_offer("c", "20000")]
        search = self.make_search()
        self.run_with_offers(search, offers)
        saved = list(search.results.order_by("rank"))
        self.assertEqual([r.rank for r in saved], [1, 2, 3])
        self.assertEqual([r.item_price for r in saved], [Decimal("10000"), Decimal("20000"), Decimal("30000")])
        self.assertEqual([r.offer.external_id for r in saved], ["b", "c", "a"])
        self.assertEqual([r.total_price for r in saved], [r.item_price for r in saved])
        self.assertTrue(all(r.delivery_price is None for r in saved))
        self.assertFalse(any(r.is_recommended for r in saved))

    def test_rerun_replaces_results(self):
        offers = [self.make_offer("a", "100"), self.make_offer("b", "200")]
        search = self.make_search()
        self.run_with_offers(search, offers)
        self.run_with_offers(search, offers)
        self.assertEqual(SearchResult.objects.filter(search=search).count(), 2)

    def test_results_limit(self):
        offers = [self.make_offer(str(i), str(100 + i)) for i in range(55)]
        search = self.make_search()
        self.run_with_offers(search, offers)
        self.assertEqual(search.results.count(), 50)
        self.assertEqual(search.results.order_by("rank").first().item_price, Decimal("100"))

    def test_results_of_other_search_are_untouched(self):
        offers = [self.make_offer("a", "100")]
        first = self.make_search()
        second = self.make_search("ноутбук")
        self.run_with_offers(first, offers)
        self.run_with_offers(second, [])
        self.assertEqual(first.results.count(), 1)
        self.assertEqual(second.results.count(), 0)


class FailureTests(PipelineBase):
    def test_error_marks_search_failed(self):
        search = self.make_search()
        with patch("catalog.services.search_products", side_effect=RuntimeError("boom")), \
                self.assertLogs("search.tasks", level="ERROR"):
            run_search(str(search.id))
        search.refresh_from_db()
        self.assertEqual(search.status, "failed")
        self.assertEqual(search.step, "")
        self.assertIsNotNone(search.finished_at)

    def test_error_does_not_break_http_flow(self):
        with patch("catalog.services.search_products", side_effect=RuntimeError("boom")), \
                self.assertLogs("search.tasks", level="ERROR"):
            response = self.client.post(reverse("search:start"), {"query": "смартфон"})
        search = SearchRequest.objects.get()
        self.assertRedirects(response, reverse("search:wait", args=[search.id]))
        self.assertEqual(self.client.get(reverse("search:status", args=[search.id])).json()["status"], "failed")


class ResultsViewTests(PipelineBase):
    def start_search(self, offers):
        with patch("catalog.services.search_products", return_value=[self.product]), \
                patch("catalog.services.get_offers", return_value=offers):
            self.client.post(reverse("search:start"), {"query": "смартфон Samsung до 50000"})
        return SearchRequest.objects.get()

    def test_items_are_built_from_saved_results(self):
        offers = [self.make_offer("a", "20000"), self.make_offer("b", "10500")]
        search = self.start_search(offers)
        response = self.client.get(reverse("search:results", args=[search.id]))
        items = response.context["items"]
        self.assertEqual([i["offer_id"] for i in items], [offers[1].id, offers[0].id])
        self.assertEqual(items[0]["shop"], "Тестовый магазин")
        self.assertEqual(items[0]["title"], "Offer b")
        self.assertEqual(items[0]["price"], "10\u00a0500")
        self.assertEqual(items[0]["total"], "10\u00a0500")
        self.assertEqual(items[0]["delivery"], "—")
        self.assertEqual(response.context["warnings"], [])

    def test_warning_when_nothing_found(self):
        search = self.start_search([])
        response = self.client.get(reverse("search:results", args=[search.id]))
        self.assertEqual(response.context["items"], [])
        self.assertEqual(response.context["warnings"], ["Результаты пока не рассчитываются"])

    def test_foreign_results_are_hidden(self):
        other = SearchRequest.objects.create(raw_query="x", session_key="other")
        self.assertEqual(self.client.get(reverse("search:results", args=[other.id])).status_code, 404)
