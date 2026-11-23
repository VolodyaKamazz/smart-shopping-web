from django import forms
from django.contrib import admin
from django.db.models import Count

from delivery.models import ShopDeliveryRule

from . import models
from .terms import PAYMENT_METHODS

admin.site.site_header = "Умный Шопинг — администрирование"
admin.site.site_title = "Умный Шопинг"
admin.site.index_title = "Каталог, магазины, доставка, импорт"


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent")
    list_filter = ("parent",)
    search_fields = ("name", "slug", "keywords")
    ordering = ("parent_id", "name")
    list_select_related = ("parent",)


@admin.register(models.Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized_name")
    search_fields = ("name", "normalized_name")
    ordering = ("name",)


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "brand", "model", "gtin", "offers_count")
    list_filter = ("category", "brand")
    search_fields = ("name", "model", "gtin", "mpn", "match_key")
    list_select_related = ("category", "brand")
    ordering = ("name",)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_offers=Count("offers"))

    @admin.display(description="Предложений", ordering="_offers")
    def offers_count(self, obj):
        return obj._offers


class ShopDeliveryRuleInline(admin.TabularInline):
    model = ShopDeliveryRule
    extra = 0
    fields = ("city", "method", "cost", "free_from", "min_days", "max_days", "is_active")
    autocomplete_fields = ("city",)


class ShopAdminForm(forms.ModelForm):
    payment_methods = forms.MultipleChoiceField(label="Способы оплаты", choices=PAYMENT_METHODS,
                                                widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = models.Shop
        fields = "__all__"


@admin.register(models.Shop)
class ShopAdmin(admin.ModelAdmin):
    form = ShopAdminForm
    fieldsets = (
        (None, {"fields": ("name", "url", "origin_city", "is_active")}),
        ("Условия для покупателя", {"fields": ("rating", "rating_count", "return_days", "warranty_months",
                                               "payment_methods")}),
        ("Импорт", {"fields": ("feed_url", "refresh_hours", "category_map", "last_import_at")}),
    )
    list_display = ("name", "url", "rating", "rating_count", "return_days", "warranty_months", "origin_city",
                    "refresh_hours", "last_import_at", "data_is_stale", "is_active", "offers_count")
    list_filter = ("is_active", "origin_city")
    search_fields = ("name", "url", "feed_url")
    list_select_related = ("origin_city",)
    autocomplete_fields = ("origin_city",)
    inlines = [ShopDeliveryRuleInline]
    actions = ["activate", "deactivate"]
    ordering = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_offers=Count("offers"))

    @admin.display(description="Предложений", ordering="_offers")
    def offers_count(self, obj):
        return obj._offers

    @admin.display(description="Данные устарели", boolean=True)
    def data_is_stale(self, obj):
        return obj.has_stale_data()

    @admin.action(description="Включить выбранные магазины")
    def activate(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"Включено магазинов: {n}")

    @admin.action(description="Отключить выбранные магазины")
    def deactivate(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"Отключено магазинов: {n}")


@admin.register(models.Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("title_raw", "shop", "product", "price", "old_price", "in_stock", "warranty_months", "is_active",
                    "last_seen_at")
    list_filter = ("shop", "is_active", "in_stock")
    search_fields = ("title_raw", "external_id", "product__name", "product__model")
    list_select_related = ("shop", "product")
    raw_id_fields = ("product",)
    readonly_fields = ("content_hash", "last_seen_at", "updated_at")
    ordering = ("shop", "title_raw")
    list_per_page = 50


@admin.register(models.PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("offer", "price", "in_stock", "recorded_at")
    list_filter = ("offer__shop", "in_stock")
    search_fields = ("offer__title_raw", "offer__external_id")
    list_select_related = ("offer", "offer__shop")
    raw_id_fields = ("offer",)
    date_hierarchy = "recorded_at"
    ordering = ("-recorded_at",)
    list_per_page = 50
