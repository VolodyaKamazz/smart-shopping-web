import uuid

from django.db import IntegrityError, transaction
from django.db.models import Min, Q

from .models import Favorite

TOKEN_KEY = "favorites_token"


def session_token(request, create=False):
    token = request.session.get(TOKEN_KEY)
    if token or not create:
        return token
    token = uuid.uuid4().hex
    request.session[TOKEN_KEY] = token
    return token


def favorites_for(request):
    if request.user.is_authenticated:
        return Favorite.objects.filter(user=request.user)
    token = session_token(request)
    if not token:
        return Favorite.objects.none()
    return Favorite.objects.filter(user__isnull=True, session_token=token)


def favorite_product_ids(request):
    return set(favorites_for(request).values_list("product_id", flat=True))


def usable_offer(product, offer):
    if offer is not None and offer.product_id == product.id and offer.is_active:
        return offer
    return None


def fixed_price(product, offer=None):
    offer = usable_offer(product, offer)
    if offer is not None:
        return offer.price
    return product.offers.filter(is_active=True, in_stock=True).aggregate(low=Min("price"))["low"]


def toggle_favorite(request, product, offer=None):
    existing = favorites_for(request).filter(product=product).first()
    if existing is not None:
        existing.delete()
        return None
    owner = {"user": request.user} if request.user.is_authenticated else {"session_token": session_token(request, create=True)}
    offer = usable_offer(product, offer)
    try:
        with transaction.atomic():
            return Favorite.objects.create(product=product, offer=offer, price_at_add=fixed_price(product, offer), **owner)
    except IntegrityError:
        return favorites_for(request).filter(product=product).first()


def current_price(favorite):
    offer = favorite.offer
    if offer is not None and offer.is_active:
        return offer.price
    return getattr(favorite, "lowest_price", None)


def favorites_with_prices(request):
    lowest = Min("product__offers__price", filter=Q(product__offers__is_active=True, product__offers__in_stock=True))
    return (favorites_for(request)
            .select_related("product", "offer__shop")
            .annotate(lowest_price=lowest)
            .order_by("-created_at", "-id"))


def claim_session_favorites(request, user):
    token = request.session.get(TOKEN_KEY)
    if not token:
        return 0
    moved = 0
    for favorite in Favorite.objects.filter(user__isnull=True, session_token=token):
        if Favorite.objects.filter(user=user, product_id=favorite.product_id).exists():
            favorite.delete()
            continue
        favorite.user = user
        favorite.session_token = ""
        favorite.save(update_fields=["user", "session_token"])
        moved += 1
    request.session.pop(TOKEN_KEY, None)
    return moved
