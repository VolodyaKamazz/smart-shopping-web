from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_delete, post_migrate, post_save, pre_save


def create_cache_table(sender, using, **kwargs):
    call_command("createcachetable", database=using, verbosity=0)


class DeliveryConfig(AppConfig):
    name = "delivery"

    def ready(self):
        from . import signals
        from .models import ZoneRate

        post_migrate.connect(create_cache_table, sender=self)
        pre_save.connect(signals.remember_rate_pair, sender=ZoneRate)
        post_save.connect(signals.drop_cache_for_rate, sender=ZoneRate)
        post_delete.connect(signals.drop_cache_for_rate, sender=ZoneRate)
