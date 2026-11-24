from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "search"

    def ready(self):
        from . import signals  # noqa: F401
