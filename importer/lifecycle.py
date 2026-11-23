from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from catalog.models import Offer, Shop

from .models import ImportRun

RUN_ABANDONED_AFTER = timedelta(minutes=30)


def start_run(shop) -> tuple[ImportRun, bool]:
    with transaction.atomic():
        Shop.objects.select_for_update().get(pk=shop.pk)
        close_abandoned_runs(shop, timezone.now())
        running = find_running_run(shop)
        if running is not None:
            return running, False
        return ImportRun.objects.create(shop=shop), True


def close_abandoned_runs(shop, now) -> int:
    return ImportRun.objects.filter(shop=shop, status="running", started_at__lt=now - RUN_ABANDONED_AFTER).update(
        status="failed", finished_at=now, error="Запуск прерван: процесс остановился до завершения импорта")


def find_running_run(shop):
    return ImportRun.objects.filter(shop=shop, status="running").order_by("-started_at").first()


def previous_success_start(shop, run):
    return (ImportRun.objects.filter(shop=shop, status="success", started_at__lt=run.started_at)
            .order_by("-started_at").values_list("started_at", flat=True).first())


def deactivate_missing(shop, threshold) -> int:
    return Offer.objects.filter(shop=shop, is_active=True, last_seen_at__lt=threshold).update(is_active=False)
