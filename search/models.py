import uuid

from django.conf import settings
from django.db import models


class SearchRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    session_key = models.CharField(max_length=40, blank=True)
    raw_query = models.CharField(max_length=300)
    parsed = models.JSONField(default=dict, blank=True)
    city = models.ForeignKey("delivery.City", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, default="new",
                              choices=[("new", "Новый"), ("running", "Выполняется"), ("done", "Готов"), ("failed", "Ошибка")])
    step = models.CharField(max_length=100, blank=True)
    degraded = models.BooleanField(default=False)
    recommended_offer = models.ForeignKey("catalog.Offer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    explanation = models.TextField(blank=True)
    facts = models.JSONField(default=dict, blank=True)
    helpful = models.BooleanField(null=True, blank=True)
    feedback_comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self):
        return self.raw_query


class SearchResult(models.Model):
    search = models.ForeignKey(SearchRequest, on_delete=models.CASCADE, related_name="results")
    offer = models.ForeignKey("catalog.Offer", on_delete=models.CASCADE)
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    breakdown = models.JSONField(default=dict, blank=True)
    item_price = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    delivery_min_days = models.PositiveSmallIntegerField(null=True, blank=True)
    delivery_max_days = models.PositiveSmallIntegerField(null=True, blank=True)
    delivery_source = models.CharField(max_length=10, blank=True)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_recommended = models.BooleanField(default=False)

    class Meta:
        ordering = ["rank"]
        indexes = [models.Index(fields=["search", "rank"])]


class OfferClick(models.Model):
    offer = models.ForeignKey("catalog.Offer", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    session_key = models.CharField(max_length=40, blank=True)
    search = models.ForeignKey(SearchRequest, null=True, blank=True, on_delete=models.SET_NULL)
    clicked_at = models.DateTimeField(auto_now_add=True)
