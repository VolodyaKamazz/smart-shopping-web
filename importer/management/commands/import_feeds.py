from django.core.management.base import BaseCommand

from importer.tasks import import_feeds


class Command(BaseCommand):
    help = "Импорт фидов магазинов (ручной запуск; по расписанию — через Django-Q2)"

    def handle(self, *args, **options):
        try:
            import_feeds()
        except NotImplementedError:
            self.stdout.write("Импорт ещё не реализован")
