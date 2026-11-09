from django.test import SimpleTestCase

from importer.models import ImportRun


class ImportRunSummaryTests(SimpleTestCase):
    def test_summary_has_fixed_order_whatever_the_key_order(self):
        run = ImportRun(stats={"errors": 3, "unchanged": 2, "updated": 1, "created": 16})  # так отдаёт JSONB
        self.assertEqual(run.summary(), "создано 16, обновлено 1, без изменений 2, ошибок 3")

    def test_summary_ignores_other_keys_and_empty_stats(self):
        self.assertEqual(ImportRun(stats={"created": 1, "error_samples": ["1: нет цены"]}).summary(), "создано 1")
        self.assertEqual(ImportRun(stats={}).summary(), "")