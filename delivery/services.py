from .info import SOURCE_UNKNOWN, DeliveryInfo
from .shop_rules import load_rules, shop_delivery_options
from .zones import zone_delivery

DEFAULT_PRIORITY = "balanced"
OPTION_KEYS = {
    "price": lambda info: (info.price, info.max_days),
    "speed": lambda info: (info.max_days, info.price),
}


class DeliveryContext:
    def __init__(self, offers, city):
        self.rules = load_rules({offer.shop_id for offer in offers}, city)
        self.zone_memo = {}


def unknown_delivery():
    return DeliveryInfo(None, None, None, SOURCE_UNKNOWN, "")


def choose_option(options, priority=DEFAULT_PRIORITY):
    return min(options, key=OPTION_KEYS.get(priority, OPTION_KEYS["price"]))


def calc_delivery_options(offer, city, context=None):
    if context is None:
        context = DeliveryContext([offer], city)
    options = shop_delivery_options(offer, context.rules.get(offer.shop_id, {}))
    if options:
        return options
    zone_option = zone_delivery(offer, city, context.zone_memo)
    return [zone_option] if zone_option is not None else [unknown_delivery()]


def calc_delivery(offer, city, priority=DEFAULT_PRIORITY, context=None) -> DeliveryInfo:
    return choose_option(calc_delivery_options(offer, city, context), priority)
