import io
from datetime import timedelta

from django.core.management import call_command
from django.db.models.signals import post_save
from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule

from catalog.models import Shop
from importer.schedule import IMPORT_FUNC, delete_shop_schedule, schedule_name, sync_all_schedules, sync_shop_schedule

from .helpers import make_shop


class SyncShopScheduleTests(TestCase):
    def test_reports_what_it_did(self):
        shop = make_shop(refresh_hours=6)
        Schedule.objects.filter(name=schedule_name(shop.pk)).delete()
        self.assertEqual(sync_shop_schedule(shop), "created")
        self.assertEqual(sync_shop_schedule(shop), "unchanged")
        shop.refresh_hours = 12
        self.assertEqual(sync_shop_schedule(shop), "updated")
        self.assertEqual(Schedule.objects.get(name=schedule_name(shop.pk)).minutes, 720)

    def test_unchanged_schedule_costs_one_query_and_no_writes(self):
        shop = make_shop()
        with self.assertNumQueries(1):
            sync_shop_schedule(shop)

    def test_wrong_function_or_args_are_repaired_but_next_run_is_kept(self):
        shop = make_shop()
        future = timezone.now() + timedelta(hours=2)
        Schedule.objects.filter(name=schedule_name(shop.pk)).update(func="math.sqrt", args="4", next_run=future)
        self.assertEqual(sync_shop_schedule(shop), "updated")
        schedule = Schedule.objects.get(name=schedule_name(shop.pk))
        self.assertEqual((schedule.func, schedule.args, schedule.next_run), (IMPORT_FUNC, str(shop.pk), future))

    def test_fixture_loading_does_not_touch_the_schedule(self):
        shop = make_shop()
        delete_shop_schedule(shop.pk)
        post_save.send(sender=Shop, instance=shop, created=True, raw=True, using="default")
        self.assertFalse(Schedule.objects.filter(name=schedule_name(shop.pk)).exists())

    def test_deleting_shops_with_queryset_removes_their_schedules(self):
        shops = [make_shop("Первый"), make_shop("Второй")]
        Shop.objects.all().delete()
        self.assertFalse(Schedule.objects.filter(name__in=[schedule_name(shop.pk) for shop in shops]).exists())


class SyncAllSchedulesTests(TestCase):
    def test_counts(self):
        first, second, third = make_shop("Первый"), make_shop("Второй"), make_shop("Третий", refresh_hours=2)
        Schedule.objects.filter(name=schedule_name(first.pk)).delete()
        Shop.objects.filter(pk=second.pk).update(refresh_hours=1)
        stats = sync_all_schedules()
        self.assertEqual((stats["created"], stats["updated"], stats["unchanged"], stats["deleted"]), (1, 1, 1, 0))
        self.assertEqual(Schedule.objects.get(name=schedule_name(third.pk)).minutes, 120)

    def test_schedules_of_missing_shops_are_removed(self):
        Schedule.objects.create(name=schedule_name(999999), func=IMPORT_FUNC, args="999999")
        stats = sync_all_schedules()
        self.assertEqual(stats["deleted"], 1)
        self.assertFalse(Schedule.objects.filter(name=schedule_name(999999)).exists())

    def test_foreign_schedules_are_never_removed(self):
        Schedule.objects.create(name="Импорт всех магазинов", func=IMPORT_FUNC)  # своя запись без префикса
        Schedule.objects.create(name="чужое", func="math.sqrt", args="4")
        sync_all_schedules()
        self.assertEqual(Schedule.objects.filter(name__in=["Импорт всех магазинов", "чужое"]).count(), 2)

    def test_no_shops(self):
        self.assertEqual(sum(sync_all_schedules().values()), 0)

    def test_command_prints_the_counts(self):
        make_shop()
        Schedule.objects.all().delete()
        Schedule.objects.create(name=schedule_name(999999), func=IMPORT_FUNC)
        out = io.StringIO()
        call_command("sync_import_schedule", stdout=out)
        self.assertIn("создано 1, изменено 0, без изменений 0, удалено лишних 1", out.getvalue())