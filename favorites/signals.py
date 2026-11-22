from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .owners import claim_session_favorites


@receiver(user_logged_in)
def move_session_favorites(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        claim_session_favorites(request, user)
