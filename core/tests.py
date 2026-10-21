from django.test import SimpleTestCase
from django.urls import reverse


class PagesTests(SimpleTestCase):
    def test_home_page_ok(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_results_page_ok(self):
        self.assertEqual(self.client.get(reverse("results")).status_code, 200)
