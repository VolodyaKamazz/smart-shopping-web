from django.apps import AppConfig


class FavoritesConfig(AppConfig):
    name = "favorites"

    def ready(self):
        from . import signals  # noqa: F401
