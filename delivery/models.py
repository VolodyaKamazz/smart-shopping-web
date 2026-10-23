from django.db import models


class City(models.Model):
    name = models.CharField(max_length=120)
    region = models.CharField(max_length=120, blank=True)
    cdek_code = models.IntegerField(null=True, blank=True)
    zone = models.PositiveSmallIntegerField(default=1, help_text="Зона для оценки доставки по таблице ZoneRate")

    def __str__(self):
        return self.name


class ShopDeliveryRule(models.Model):
    shop = models.ForeignKey("catalog.Shop", on_delete=models.CASCADE, related_name="delivery_rules")
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.CASCADE, help_text="Пусто — правило по умолчанию")
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    free_from = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()


class ZoneRate(models.Model):
    zone_from = models.PositiveSmallIntegerField()
    zone_to = models.PositiveSmallIntegerField()
    max_weight_kg = models.DecimalField(max_digits=6, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()
