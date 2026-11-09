import io
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from catalog.models import Offer, Shop
from importer.models import ImportRun

from .helpers import feed_xml, make_client, make_shop, many_offers_feed, offer_xml


class ImportFeedsCommandTests(TestCase):
    def setUp(self):
        self.alpha = make_shop("Альфа")
        self.beta = make_shop("Beta")
        self.routes = {self.alpha.feed_url: many_offers_feed(2), self.beta.feed_url: many_offers_feed(3)}

    def run_command(self, *args, routes=None, warnings=False):
        out = io.StringIO()
        client = make_client(routes or self.routes)
        with mock.patch("importer.tasks.make_client", return_value=client):
            if warnings:
                with self.assertLogs("importer"):
                    call_command("import_feeds", *args, stdout=out)
            else:
                call_command("import_feeds", *args, stdout=out)
        return out.getvalue()

    def test_imports_all_active_shops_and_prints_summary(self):
        output = self.run_command()
        self.assertIn("Альфа: успешно, создано 2, обновлено 0, без изменений 0, ошибок 0", output)
        self.assertIn("Beta: успешно, создано 3, обновлено 0, без изменений 0, ошибок 0", output)
        self.assertEqual(Offer.objects.count(), 5)

    def test_second_run_reports_unchanged(self):
        self.run_command()
        self.assertIn("Альфа: успешно, создано 0, обновлено 0, без изменений 2, ошибок 0", self.run_command())

    def test_shop_by_name_in_any_case(self):
        output = self.run_command("--shop", "BETA")
        self.assertIn("Beta: успешно", output)
        self.assertNotIn("Альфа", output)
        self.assertEqual(ImportRun.objects.count(), 1)

    def test_shop_by_id(self):
        output = self.run_command("--shop", str(self.alpha.pk))
        self.assertIn("Альфа: успешно", output)
        self.assertEqual(ImportRun.objects.count(), 1)

    def test_unknown_shop_is_an_error(self):
        for value in ("Нет такого", "999999", "99999999999999999999", "²"):
            with self.subTest(shop=value), self.assertRaisesMessage(CommandError, "не найден"):
                call_command("import_feeds", "--shop", value, stdout=io.StringIO())
        self.assertEqual(ImportRun.objects.count(), 0)

    def test_ambiguous_name_is_an_error(self):
        make_shop("beta")
        with self.assertRaisesMessage(CommandError, "неоднозначно"):
            call_command("import_feeds", "--shop", "Beta", stdout=io.StringIO())

    def test_failed_import_is_printed_and_exits_with_error(self):
        out = io.StringIO()
        client = make_client({self.alpha.feed_url: 500, self.beta.feed_url: many_offers_feed(3)})
        with mock.patch("importer.tasks.make_client", return_value=client), self.assertLogs("importer"), \
                self.assertRaisesMessage(CommandError, "Альфа"):
            call_command("import_feeds", stdout=out)
        self.assertIn("Альфа: ошибка, HTTPStatusError", out.getvalue())
        self.assertIn("Beta: успешно", out.getvalue())  # остальные магазины всё равно загружены

    def test_skipped_records_do_not_fail_the_command(self):
        routes = {**self.routes, self.alpha.feed_url: feed_xml(offer_xml("ok"), offer_xml("bad", price=None))}
        output = self.run_command(routes=routes, warnings=True)
        self.assertIn("Альфа: успешно, создано 1, обновлено 0, без изменений 0, ошибок 1", output)

    def test_nothing_to_import(self):
        Shop.objects.update(is_active=False)
        self.assertIn("Нечего импортировать", self.run_command())