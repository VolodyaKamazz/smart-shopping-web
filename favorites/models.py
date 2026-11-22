from django.conf import settings
from django.db import models
from django.db.models import Q


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    session_token = models.CharField(max_length=32, blank=True, db_index=True)
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    offer = models.ForeignKey("catalog.Offer", null=True, blank=True, on_delete=models.SET_NULL)
    price_at_add = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    target_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    last_notified_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], condition=Q(user__isnull=False),
                                    name="uniq_favorite_user_product"),
            models.UniqueConstraint(fields=["session_token", "product"], condition=Q(user__isnull=True),
                                    name="uniq_favorite_session_product"),
            models.CheckConstraint(condition=Q(user__isnull=False) | ~Q(session_token=""),
                                   name="favorite_has_owner"),
        ]


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
