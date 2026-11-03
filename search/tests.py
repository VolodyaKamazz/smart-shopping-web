from django.test import TestCase
from django.urls import reverse

from .models import SearchRequest


class SearchFlowTests(TestCase):
    def test_home(self):
        self.assertEqual(self.client.get(reverse("search:home")).status_code, 200)

    def test_full_stub_flow(self):
        r = self.client.post(reverse("search:start"), {"query": "смартфон до 50000"})
        search = SearchRequest.objects.get()
        self.assertRedirects(r, reverse("search:wait", args=[search.id]))
        data = self.client.get(reverse("search:status", args=[search.id])).json()
        self.assertEqual(data["status"], "done")
        self.assertEqual(self.client.get(data["redirect_url"]).status_code, 200)

    def test_foreign_search_is_hidden(self):
        s = SearchRequest.objects.create(raw_query="x", session_key="other")
        self.assertEqual(self.client.get(reverse("search:wait", args=[s.id])).status_code, 404)


class SearchFormTests(TestCase):
    def test_form_markup(self):
        html = self.client.get(reverse("search:home")).content.decode()
        self.assertIn('method="post"', html)
        self.assertIn('name="query"', html)
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn(f'action="{reverse("search:start")}"', html)

    def test_post_without_csrf_token_is_rejected(self):
        from django.test import Client
        r = Client(enforce_csrf_checks=True).post(reverse("search:start"), {"query": "ноутбук"})
        self.assertEqual(r.status_code, 403)

    def test_empty_query_redirects_home(self):
        r = self.client.post(reverse("search:start"), {"query": "   "})
        self.assertRedirects(r, reverse("search:home"))
