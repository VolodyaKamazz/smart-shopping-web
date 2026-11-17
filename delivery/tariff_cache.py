from django.core.cache import cache

from .weights import WEIGHT_CLASSES_KG

CACHE_TTL = 24 * 60 * 60


def _key(zone_from, zone_to, weight_class):
    return f"delivery:zone:{zone_from}:{zone_to}:{weight_class}"


def get_tariff(zone_from, zone_to, weight_class):
    return cache.get(_key(zone_from, zone_to, weight_class))


def put_tariff(zone_from, zone_to, weight_class, info):
    cache.set(_key(zone_from, zone_to, weight_class), info, CACHE_TTL)


def drop_tariffs(zone_from, zone_to):
    cache.delete_many([_key(zone_from, zone_to, weight_class) for weight_class in WEIGHT_CLASSES_KG])
