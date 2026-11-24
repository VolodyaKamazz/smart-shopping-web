from delivery.models import City

SESSION_KEY = "city_id"


def city_from(raw):
    raw = str(raw or "").strip()
    return City.objects.filter(pk=int(raw)).first() if raw.isascii() and raw.isdigit() else None


def guest_city(request):
    pk = request.session.get(SESSION_KEY)
    return City.objects.filter(pk=pk).first() if pk else None


def current_city(request):
    if request.user.is_authenticated:
        return request.user.city
    return guest_city(request)


def remember_city(request, city):
    if request.user.is_authenticated:
        request.user.city = city
        request.user.save(update_fields=["city"])
    elif city is None:
        request.session.pop(SESSION_KEY, None)
    else:
        request.session[SESSION_KEY] = city.pk
