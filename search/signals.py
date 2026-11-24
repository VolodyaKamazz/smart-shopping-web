from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .city import SESSION_KEY, guest_city


@receiver(user_logged_in)
def keep_guest_city(sender, request, user, **kwargs):
    if request is None or not hasattr(request, "session") or user.city_id:
        return
    city = guest_city(request)
    if city is not None:
        user.city = city
        user.save(update_fields=["city"])
    request.session.pop(SESSION_KEY, None)
