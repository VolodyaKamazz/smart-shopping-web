from .models import ZoneRate
from .tariff_cache import drop_tariffs


def remember_rate_pair(sender, instance, raw=False, **kwargs):
    instance._previous_pair = None
    if instance.pk and not raw:
        instance._previous_pair = (ZoneRate.objects.filter(pk=instance.pk)
                                   .values_list("zone_from", "zone_to").first())


def drop_cache_for_rate(sender, instance, raw=False, **kwargs):
    if raw:
        return
    pairs = {(instance.zone_from, instance.zone_to)}
    previous = getattr(instance, "_previous_pair", None)
    if previous is not None:
        pairs.add(previous)
    for zone_from, zone_to in pairs:
        drop_tariffs(zone_from, zone_to)
