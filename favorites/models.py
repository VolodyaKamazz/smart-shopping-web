from django.conf import settings
from django.db import models


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    target_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    last_notified_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="uniq_favorite_user_product")]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    offer = models.ForeignKey("catalog.Offer", null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=20, default="price_drop")
    message = models.CharField(max_length=300)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "is_read"])]
