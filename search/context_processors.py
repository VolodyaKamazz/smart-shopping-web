from django.utils.functional import SimpleLazyObject

from delivery.models import City

from .city import current_city


def location(request):
    return {
        "cities": SimpleLazyObject(lambda: list(City.objects.order_by("name").only("id", "name"))),
        "current_city": SimpleLazyObject(lambda: current_city(request)),
    }
