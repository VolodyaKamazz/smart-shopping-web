from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Shop
from importer.models import ImportRun


class ImportRunAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("root", "root@example.com", "pass-12345-x")
        shop = Shop.objects.create(name="DNS")
        cls.ok = ImportRun.objects.create(
            shop=shop, status="success",
            stats={"created": 16, "updated": 1, "unchanged": 2, "errors": 3, "error_samples": ["DN-ERR-1: нет цены"]})
        cls.failed = ImportRun.objects.create(shop=shop, status="failed", error="HTTPStatusError: 500")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_list_shows_russian_stats(self):
        response = self.client.get(reverse("admin:importer_importrun_changelist"))
        self.assertContains(response, "создано 16, обновлено 1, без изменений 2, ошибок 3")

    def test_run_page_shows_skipped_records(self):
        response = self.client.get(reverse("admin:importer_importrun_change", args=[self.ok.pk]))
        self.assertContains(response, "DN-ERR-1")

    def test_failed_run_page_shows_error(self):
        response = self.client.get(reverse("admin:importer_importrun_change", args=[self.failed.pk]))
        self.assertContains(response, "HTTPStatusError: 500")

    def test_search_by_error_text(self):
        response = self.client.get(reverse("admin:importer_importrun_changelist"), {"q": "HTTPStatusError"})
        self.assertEqual(list(response.context["cl"].result_list), [self.failed])
