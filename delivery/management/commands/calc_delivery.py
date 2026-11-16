from django.core.management.base import BaseCommand, CommandError

from catalog.models import Offer, Shop
from delivery.info import SOURCE_SHOP, SOURCE_UNKNOWN, SOURCE_ZONE, format_days
from delivery.models import City, DeliveryMethod
from delivery.services import DEFAULT_PRIORITY, OPTION_KEYS, calc_delivery_options, choose_option
from delivery.weights import offer_weight_class

SOURCE_LABELS = {
    SOURCE_SHOP: "правило магазина",
    SOURCE_ZONE: "таблица зон ≈",
    SOURCE_UNKNOWN: "условия уточняются",
}
METHOD_LABELS = {**dict(DeliveryMethod.choices), "": "способ не определён"}


def format_option(info):
    if not info.is_known:
        return f"{METHOD_LABELS[info.method]}: {SOURCE_LABELS[info.source]}"
    price = "бесплатно" if info.price == 0 else f"{info.price} ₽"
    days = format_days(info.min_days, info.max_days)
    return f"{METHOD_LABELS[info.method]}: {price}, {days} дн. ({SOURCE_LABELS[info.source]})"


class Command(BaseCommand):
    help = "Показывает варианты доставки в выбранный город: по одному предложению каждого магазина или по --offer"

    def add_arguments(self, parser):
        parser.add_argument("city", nargs="+")
        parser.add_argument("--offer", type=int)
        parser.add_argument("--priority", choices=[DEFAULT_PRIORITY, *OPTION_KEYS], default=DEFAULT_PRIORITY)

    def handle(self, *args, **options):
        city = self.find_city(" ".join(options["city"]))
        offers = self.pick_offers(options["offer"])
        if not offers:
            self.stdout.write(self.style.WARNING("Предложений нет, выполните: python manage.py import_feeds"))
            return
        self.stdout.write(f"Город: {city.name}, зона {city.zone}, приоритет: {options['priority']}")
        for offer in offers:
            options_list = calc_delivery_options(offer, city)
            chosen = choose_option(options_list, options["priority"])
            self.stdout.write(f"{offer.shop.name}: {offer.title_raw[:60]}, {offer.price} ₽, "
                              f"класс веса {offer_weight_class(offer)} кг")
            for info in options_list:
                self.stdout.write(f"  {'→' if info is chosen else ' '} {format_option(info)}")

    @staticmethod
    def find_city(name):
        for city in City.objects.order_by("pk"):
            if city.name.casefold() == name.casefold():
                return city
        raise CommandError(f"Город не найден: {name}")

    @staticmethod
    def pick_offers(offer_id):
        offers = Offer.objects.select_related("shop__origin_city", "product__category__parent")
        if offer_id is not None:
            offer = offers.filter(pk=offer_id).first()
            if offer is None:
                raise CommandError(f"Предложение не найдено: {offer_id}")
            return [offer]
        picked = []
        for shop in Shop.objects.filter(is_active=True).order_by("pk"):
            offer = offers.filter(shop=shop, is_active=True, in_stock=True).order_by("price", "pk").first()
            if offer is not None:
                picked.append(offer)
        return picked
