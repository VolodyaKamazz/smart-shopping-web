from django.core.management.base import BaseCommand, CommandError

from catalog.models import Shop
from importer.models import ImportRun
from importer.tasks import import_feeds


class Command(BaseCommand):
    help = ("Импорт фидов магазинов (ручной запуск; по расписанию — через Django-Q2). "
            "Фид скачивается по Shop.feed_url, для демо-фидов должен работать runserver.")

    def add_arguments(self, parser):
        parser.add_argument("--shop", help="id или название магазина; без параметра — все активные")

    def handle(self, *args, **options):
        shop_id = self._find_shop(options["shop"]).pk if options["shop"] else None
        run_ids = import_feeds(shop_id)
        if not run_ids:
            self.stdout.write("Нечего импортировать: нет активных магазинов с адресом фида")
            return

        failed = []
        for run in ImportRun.objects.filter(pk__in=run_ids).select_related("shop").order_by("pk"):
            if run.status == "success":
                self.stdout.write(self.style.SUCCESS(f"{run.shop.name}: успешно, {run.summary()}"))
            else:
                failed.append(run.shop.name)
                status = run.get_status_display().lower()
                self.stdout.write(self.style.ERROR(f"{run.shop.name}: {status}, {run.error}"))
        if failed:
            raise CommandError("Импорт не удался: " + ", ".join(failed))

    def _find_shop(self, value: str) -> Shop:
        if value.isascii() and value.isdigit():
            shops = Shop.objects.filter(pk=value)
        else:
            shops = Shop.objects.filter(name__iexact=value)
        if shops.count() != 1:
            raise CommandError(f"Магазин «{value}» не найден или название неоднозначно, укажите id")
        return shops.get()