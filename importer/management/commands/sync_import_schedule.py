from django.core.management.base import BaseCommand

from importer.schedule import sync_all_schedules


class Command(BaseCommand):
    help = ("Приводит расписание импорта в соответствие с магазинами: создаёт недостающие записи Django-Q2, "
            "исправляет периоды по refresh_hours, убирает записи удалённых магазинов. "
            "Нужна один раз после появления расписания и после массовой правки refresh_hours через update().")

    def handle(self, *args, **options):
        stats = sync_all_schedules()
        self.stdout.write(
            f"Расписание импорта: создано {stats['created']}, изменено {stats['updated']}, "
            f"без изменений {stats['unchanged']}, удалено лишних {stats['deleted']}")
