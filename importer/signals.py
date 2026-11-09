from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from catalog.models import Shop

from .schedule import delete_shop_schedule, sync_shop_schedule


@receiver(post_save, sender=Shop)
def sync_schedule_on_save(sender, instance, raw, **kwargs):
    if not raw:
        sync_shop_schedule(instance)


@receiver(post_delete, sender=Shop)
def delete_schedule_on_delete(sender, instance, **kwargs):
    delete_shop_schedule(instance.pk)
