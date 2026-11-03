from django.contrib import admin

from . import models


@admin.register(models.City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "zone", "cdek_code")
    list_editable = ("zone",)
    list_filter = ("zone", "region")
    search_fields = ("name", "region")  # также нужен для autocomplete в магазинах
    ordering = ("name",)
    list_per_page = 50


@admin.register(models.ShopDeliveryRule)
class ShopDeliveryRuleAdmin(admin.ModelAdmin):
    list_display = ("shop", "city_or_default", "cost", "free_from", "min_days", "max_days")
    list_filter = ("shop",)
    search_fields = ("shop__name", "city__name")
    list_select_related = ("shop", "city")
    autocomplete_fields = ("city",)
    ordering = ("shop", "city__name")

    @admin.display(description="Город", ordering="city__name")
    def city_or_default(self, obj):
        return obj.city.name if obj.city_id else "По умолчанию"


@admin.register(models.ZoneRate)
class ZoneRateAdmin(admin.ModelAdmin):
    list_display = ("zone_from", "zone_to", "max_weight_kg", "price", "min_days", "max_days")
    list_filter = ("zone_from", "zone_to", "max_weight_kg")
    ordering = ("zone_from", "zone_to", "max_weight_kg")
    list_per_page = 50
