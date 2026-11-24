from django.utils.functional import SimpleLazyObject

from .owners import favorites_for


def favorites(request):
    return {"favorites_count": SimpleLazyObject(lambda: favorites_for(request).count())}
