from django.contrib import admin

from . import models


@admin.register(models.Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "session_token", "price_at_add", "created_at")
    list_filter = ("created_at",)


admin.site.register(models.Notification)
