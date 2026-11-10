import json

from django.core.management.base import BaseCommand

from search.parser import parse_query
from search.tasks import load_dictionaries


class Command(BaseCommand):
    help = "Показывает, как система разбирает поисковый запрос: категория, бренд, цена, слова"

    def add_arguments(self, parser):
        parser.add_argument("query", nargs="+")

    def handle(self, *args, **options):
        text = " ".join(options["query"])
        categories, brands = load_dictionaries()
        if not categories:
            self.stdout.write(self.style.WARNING("Справочники пусты, выполните: python manage.py load_demo_data"))
        self.stdout.write(f"Запрос: {text}")
        self.stdout.write(json.dumps(parse_query(text, categories, brands), ensure_ascii=False, indent=2))
