from .info import SOURCE_UNKNOWN, DeliveryInfo
from .shop_rules import load_rules, shop_delivery_options
from .zones import zone_delivery

DEFAULT_PRIORITY = "balanced"
OPTION_KEYS = {
    "price": lambda info: (info.price, info.max_days),
    "speed": lambda info: (info.max_days, info.price),
}


def unknown_delivery():
    return DeliveryInfo(None, None, None, SOURCE_UNKNOWN, "")


def _offer_options(offer, city, shop_rules, zone_memo=None):
    options = shop_delivery_options(offer, shop_rules)
    if options:
        return options
    zone_option = zone_delivery(offer, city, zone_memo)
    return [zone_option] if zone_option is not None else [unknown_delivery()]


def choose_option(options, priority=DEFAULT_PRIORITY):
    return min(options, key=OPTION_KEYS.get(priority, OPTION_KEYS["price"]))


def calc_delivery_options(offer, city):
    return _offer_options(offer, city, load_rules([offer.shop_id], city)[offer.shop_id])


def calc_delivery(offer, city, priority=DEFAULT_PRIORITY) -> DeliveryInfo:
    return choose_option(calc_delivery_options(offer, city), priority)


def calc_deliveries(offers, city, priority=DEFAULT_PRIORITY):
    rules = load_rules({offer.shop_id for offer in offers}, city)
    zone_memo = {}
    return {offer.pk: choose_option(_offer_options(offer, city, rules[offer.shop_id], zone_memo), priority)
            for offer in offers}
