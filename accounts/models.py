from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField("e-mail", unique=True)
    city = models.ForeignKey("delivery.City", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="город")
    delivery_priority = models.CharField("приоритет", max_length=10, default="balanced",
                                         choices=[("balanced", "Баланс"), ("price", "Цена"), ("speed", "Скорость")])
    budget_max = models.DecimalField("максимальный бюджет", max_digits=12, decimal_places=2, null=True, blank=True)
