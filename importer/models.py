from django.db import models


class ImportRun(models.Model):
    shop = models.ForeignKey("catalog.Shop", on_delete=models.CASCADE, related_name="import_runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default="running",
                              choices=[("running", "Выполняется"), ("success", "Успешно"), ("partial", "Частично"), ("failed", "Ошибка")])
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
