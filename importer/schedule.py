from collections import Counter

from django_q.models import Schedule

from catalog.models import Shop

IMPORT_FUNC = "importer.tasks.import_feeds"
NAME_PREFIX = "import_feeds:"
MIN_MINUTES = 60
MAX_MINUTES = 32767


def schedule_name(shop_id: int) -> str:
    return f"{NAME_PREFIX}{shop_id}"


def _wanted_fields(shop: Shop) -> dict:
    minutes = min(max(shop.refresh_hours * 60, MIN_MINUTES), MAX_MINUTES)
    return {"func": IMPORT_FUNC, "args": str(shop.pk), "schedule_type": Schedule.MINUTES,
            "minutes": minutes, "repeats": -1}


def sync_shop_schedule(shop: Shop) -> str:
    wanted = _wanted_fields(shop)
    schedule, created = Schedule.objects.get_or_create(name=schedule_name(shop.pk), defaults=wanted)
    if created:
        return "created"
    changed = {field: value for field, value in wanted.items() if getattr(schedule, field) != value}
    if not changed:
        return "unchanged"
    Schedule.objects.filter(pk=schedule.pk).update(**changed)
    return "updated"


def delete_shop_schedule(shop_id: int) -> None:
    Schedule.objects.filter(name=schedule_name(shop_id)).delete()


def sync_all_schedules() -> Counter:
    stats = Counter()
    shops = list(Shop.objects.all())
    for shop in shops:
        stats[sync_shop_schedule(shop)] += 1
    stale = Schedule.objects.filter(name__startswith=NAME_PREFIX).exclude(
        name__in=[schedule_name(shop.pk) for shop in shops])
    stats["deleted"] = stale.count()
    stale.delete()
    return stats