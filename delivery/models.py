from django.db import models
from django.db.models import F, Q


class City(models.Model):
    name = models.CharField(max_length=120)
    region = models.CharField(max_length=120, blank=True)
    cdek_code = models.IntegerField(null=True, blank=True)
    zone = models.PositiveSmallIntegerField(default=1, help_text="Зона для оценки доставки по таблице ZoneRate")

    def __str__(self):
        return self.name


class DeliveryMethod(models.TextChoices):
    COURIER = "courier", "Курьер"
    PICKUP = "pickup", "Пункт выдачи"


class ShopDeliveryRule(models.Model):
    shop = models.ForeignKey("catalog.Shop", on_delete=models.CASCADE, related_name="delivery_rules")
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.CASCADE,
                             help_text="Пусто — правило по умолчанию")
    method = models.CharField("способ получения", max_length=10, choices=DeliveryMethod.choices,
                              default=DeliveryMethod.COURIER)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    free_from = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()
    is_active = models.BooleanField("действует", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shop", "city", "method"], name="uniq_delivery_rule_city_method"),
            models.UniqueConstraint(fields=["shop", "method"], condition=Q(city__isnull=True),
                                    name="uniq_delivery_rule_default_method"),
            models.CheckConstraint(condition=Q(min_days__lte=F("max_days")), name="delivery_rule_days_order"),
        ]

    def __str__(self):
        return f"{self.shop} · {self.get_method_display()} · {self.city or 'по умолчанию'}"


class ZoneRate(models.Model):
    zone_from = models.PositiveSmallIntegerField()
    zone_to = models.PositiveSmallIntegerField()
    max_weight_kg = models.DecimalField(max_digits=6, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["zone_from", "zone_to", "max_weight_kg"], name="uniq_zone_rate_class"),
        ]
