from django.contrib import admin

from . import models


@admin.register(models.ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    """Запуски импорта создаёт код; в админке они только для просмотра."""

    list_display = ("shop", "status", "started_at", "finished_at", "stats_summary")
    list_filter = ("status", "shop")
    search_fields = ("shop__name", "error")
    list_select_related = ("shop",)
    date_hierarchy = "started_at"
    ordering = ("-started_at",)
    readonly_fields = ("shop", "started_at", "finished_at", "status", "stats", "error")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Итоги")
    def stats_summary(self, obj):
        s = obj.stats or {}
        if not s:
            return "—"
        return ", ".join(f"{k}: {v}" for k, v in s.items())
