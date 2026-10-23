from django.contrib import admin

from . import models

admin.site.register(models.Category)
admin.site.register(models.Brand)
admin.site.register(models.Product)
admin.site.register(models.Shop)
admin.site.register(models.Offer)
admin.site.register(models.PriceHistory)
