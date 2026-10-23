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
