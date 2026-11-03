"""Загрузка демо-данных: города, зоны, тарифы ZoneRate, категории, бренды, магазины.

    python manage.py load_demo_data

Команда идемпотентна: повторный запуск обновляет записи, дубликатов не создаёт.
Товары и предложения не создаются: они появятся при импорте YML-фидов
(static/demo_feeds/*.yml), см. demo_data/README.md.
"""
import json
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Brand, Category, Shop
from delivery.models import City, ShopDeliveryRule, ZoneRate

DATA_DIR = settings.BASE_DIR / "demo_data"


def _read(name):
    path = DATA_DIR / name
    if not path.exists():
        raise CommandError(f"Не найден файл демо-данных: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Command(BaseCommand):
    help = "Загружает демо-данные (города, ZoneRate, категории, бренды, магазины с правилами доставки)"

    def handle(self, *args, **options):
        with transaction.atomic():
            stats = {
                "города": self._cities(),
                "тарифы ZoneRate": self._zone_rates(),
                "категории": self._categories(),
                "бренды": self._brands(),
            }
            shops, rules = self._shops()
            stats["магазины"] = shops
            stats["правила доставки магазинов"] = rules
        if options["verbosity"] == 0:
            return
        for label, (created, updated) in stats.items():
            self.stdout.write(f"{label}: создано {created}, обновлено {updated}")
        self.stdout.write(self.style.SUCCESS("Демо-данные загружены"))

    @staticmethod
    def _count(created_flags):
        flags = list(created_flags)
        created = sum(1 for f in flags if f)
        return created, len(flags) - created

    def _cities(self):
        def gen():
            for c in _read("cities.json"):
                _, created = City.objects.update_or_create(
                    name=c["name"], region=c["region"], defaults={"zone": c["zone"]})
                yield created
        return self._count(gen())

    def _zone_rates(self):
        def gen():
            for r in _read("zone_rates.json"):
                _, created = ZoneRate.objects.update_or_create(
                    zone_from=r["zone_from"], zone_to=r["zone_to"],
                    max_weight_kg=Decimal(r["max_weight_kg"]),
                    defaults={"price": Decimal(r["price"]), "min_days": r["min_days"], "max_days": r["max_days"]})
                yield created
        return self._count(gen())

    def _categories(self):
        def gen():
            for c in _read("categories.json"):  # родители идут раньше детей
                parent = Category.objects.get(slug=c["parent"]) if c["parent"] else None
                _, created = Category.objects.update_or_create(
                    slug=c["slug"], defaults={"name": c["name"], "parent": parent, "keywords": c["keywords"]})
                yield created
        return self._count(gen())

    def _brands(self):
        def gen():
            for b in _read("brands.json"):
                _, created = Brand.objects.update_or_create(
                    normalized_name=b["normalized_name"], defaults={"name": b["name"]})
                yield created
        return self._count(gen())

    def _shops(self):
        shop_flags, rule_flags = [], []
        for s in _read("shops.json"):
            origin = City.objects.get(name=s["origin_city"])
            shop, created = Shop.objects.update_or_create(name=s["name"], defaults={
                "url": s["url"], "origin_city": origin, "rating": Decimal(s["rating"]),
                "rating_count": s["rating_count"], "return_days": s["return_days"],
                "payment_methods": s["payment_methods"], "warranty_months": s["warranty_months"],
                "feed_url": s["feed_url"], "refresh_hours": s["refresh_hours"],
                "category_map": s["category_map"],
            })
            shop_flags.append(created)
            for r in s["delivery_rules"]:
                city = City.objects.get(name=r["city"]) if r["city"] else None
                _, created = ShopDeliveryRule.objects.update_or_create(shop=shop, city=city, defaults={
                    "cost": Decimal(r["cost"]), "free_from": Decimal(r["free_from"]),
                    "min_days": r["min_days"], "max_days": r["max_days"]})
                rule_flags.append(created)
        return self._count(shop_flags), self._count(rule_flags)
