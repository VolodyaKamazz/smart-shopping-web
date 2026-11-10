from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate


def create_cache_table(sender, using, **kwargs):
    call_command("createcachetable", database=using, verbosity=0)


class DeliveryConfig(AppConfig):
    name = "delivery"

    def ready(self):
        post_migrate.connect(create_cache_table, sender=self)
