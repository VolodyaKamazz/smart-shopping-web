from django.contrib import admin

from . import models

admin.site.register(models.SearchRequest)
admin.site.register(models.SearchResult)
admin.site.register(models.OfferClick)
