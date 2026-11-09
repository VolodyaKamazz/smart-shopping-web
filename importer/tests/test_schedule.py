import io
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule
from django_q.scheduler import scheduler

from catalog.models import Offer, Shop
from importer.models import ImportRun
from importer.schedule import MAX_MINUTES, schedule_name

from .helpers import make_client, make_shop, many_offers_feed


def create_shop(**fields) -> Shop:
    return make_shop(fields.pop("name", "Магазин"), **fields)


class ShopScheduleTests(TestCase):
    def test_new_shop_gets_schedule_from_refresh_hours(self):
        shop = create_shop(refresh_hours=4)
        schedule = Schedule.objects.get(name=schedule_name(shop.pk))
        self.assertEqual(schedule.func, "importer.tasks.import_feeds")
        self.assertEqual(schedule.args, str(shop.pk))
        self.assertEqual(schedule.schedule_type, Schedule.MINUTES)
        self.assertEqual(schedule.minutes, 240)
        self.assertEqual(schedule.repeats, -1)

    def test_default_period_is_six_hours(self):
        shop = create_shop()
        self.assertEqual(Schedule.objects.get(name=schedule_name(shop.pk)).minutes, 360)

    def test_first_run_is_due_immediately(self):
        shop = create_shop()
        self.assertLessEqual(Schedule.objects.get(name=schedule_name(shop.pk)).next_run, timezone.now())

    def test_changing_refresh_hours_updates_period_but_not_next_run(self):
        shop = create_shop(refresh_hours=6)
        future = timezone.now() + timedelta(hours=3)
        Schedule.objects.filter(name=schedule_name(shop.pk)).update(next_run=future)

        shop.refresh_hours = 12
        shop.save()

        schedule = Schedule.objects.get(name=schedule_name(shop.pk))
        self.assertEqual(schedule.minutes, 720)
        self.assertEqual(schedule.next_run, future)

    def test_saving_again_does_not_duplicate_schedule(self):
        shop = create_shop()
        shop.save()
        shop.save()
        self.assertEqual(Schedule.objects.filter(name=schedule_name(shop.pk)).count(), 1)

    def test_each_shop_has_own_schedule(self):
        first, second = create_shop(name="Первый"), create_shop(name="Второй", refresh_hours=2)
        self.assertEqual(Schedule.objects.get(name=schedule_name(first.pk)).args, str(first.pk))
        self.assertEqual(Schedule.objects.get(name=schedule_name(second.pk)).minutes, 120)

    def test_period_is_kept_in_valid_range(self):
        for hours, minutes in ((0, 60), (1, 60), (546, 32760), (547, MAX_MINUTES), (30000, MAX_MINUTES)):
            with self.subTest(hours=hours):
                shop = create_shop(refresh_hours=hours)
                self.assertEqual(Schedule.objects.get(name=schedule_name(shop.pk)).minutes, minutes)

    def test_deleting_shop_deletes_schedule(self):
        shop = create_shop()
        name = schedule_name(shop.pk)
        shop.delete()
        self.assertFalse(Schedule.objects.filter(name=name).exists())

    def test_other_schedules_are_untouched(self):
        Schedule.objects.create(name="чужое", func="math.sqrt", args="4")
        shop = create_shop()
        shop.delete()
        self.assertTrue(Schedule.objects.filter(name="чужое").exists())


class SyncScheduleCommandTests(TestCase):
    def test_creates_missing_schedules_and_is_idempotent(self):
        shops = [create_shop(name="Первый"), create_shop(name="Второй", refresh_hours=3)]
        Schedule.objects.filter(func="importer.tasks.import_feeds").delete()

        call_command("sync_import_schedule", stdout=io.StringIO())
        call_command("sync_import_schedule", stdout=io.StringIO())

        self.assertEqual(Schedule.objects.filter(func="importer.tasks.import_feeds").count(), 2)
        self.assertEqual(Schedule.objects.get(name=schedule_name(shops[1].pk)).minutes, 180)

    def test_fixes_period_after_bulk_update(self):
        shop = create_shop(refresh_hours=6)
        Shop.objects.filter(pk=shop.pk).update(refresh_hours=2)
        call_command("sync_import_schedule", stdout=io.StringIO())
        self.assertEqual(Schedule.objects.get(name=schedule_name(shop.pk)).minutes, 120)


class SchedulerRunsImportTests(TestCase):
    def test_due_schedule_imports_its_shop(self):
        due, not_due = create_shop(name="Подошёл срок"), create_shop(name="Рано")
        Schedule.objects.filter(name=schedule_name(not_due.pk)).update(next_run=timezone.now() + timedelta(hours=1))
        Schedule.objects.filter(name=schedule_name(due.pk)).update(next_run=timezone.now() - timedelta(minutes=1))

        client = make_client({due.feed_url: many_offers_feed(4), not_due.feed_url: many_offers_feed(9)})
        with mock.patch("importer.tasks.make_client", return_value=client):
            scheduler()

        run = ImportRun.objects.get()
        self.assertEqual((run.shop, run.status), (due, "success"))
        self.assertEqual(run.stats["created"], 4)
        self.assertEqual(Offer.objects.filter(shop=due).count(), 4)
        self.assertEqual(Offer.objects.filter(shop=not_due).count(), 0)
        next_run = Schedule.objects.get(name=schedule_name(due.pk)).next_run
        self.assertGreater(next_run, timezone.now() + timedelta(hours=5))