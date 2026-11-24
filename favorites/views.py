from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import Offer, Product
from search import ranking
from search.city import current_city
from search.images import image_of

from . import owners
from .models import Notification


def _money(value):
    return f"{value:,.0f}".replace(",", "\u00a0")


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


def _offer_from(request):
    raw = request.POST.get("offer_id", "")
    return Offer.objects.filter(pk=int(raw)).first() if raw.isascii() and raw.isdigit() else None


@require_POST
def toggle(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    favorite = owners.toggle_favorite(request, product, _offer_from(request))
    if _wants_json(request):
        return JsonResponse({
            "is_favorite": favorite is not None,
            "product_id": product.id,
            "price_at_add": None if favorite is None or favorite.price_at_add is None else float(favorite.price_at_add),
            "favorites_count": owners.favorites_for(request).count(),
        })
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("favorites:list")


def _shown_offer(favorite):
    offer = favorite.offer
    if offer is not None and offer.is_active:
        return offer
    return (favorite.product.offers.filter(is_active=True, in_stock=True, shop__is_active=True)
            .select_related("shop").order_by("price").first())


def _known(info):
    return info is not None and info.price is not None


def _delivery_line(info):
    if not _known(info):
        return "уточняется"
    price = "бесплатно" if info.price == 0 else f"{_money(info.price)} ₽"
    low, high = info.min_days, info.max_days
    if low is None or high is None:
        return price
    return f"{price}, {low} дн." if low == high else f"{price}, {low}–{high} дн."


def _row(favorite, shown, infos, city):
    current = owners.current_price(favorite)
    fixed = favorite.price_at_add
    diff = None if current is None or fixed is None else current - fixed
    info = infos.get(shown.id) if shown is not None else None
    delivery = ""
    total = ""
    if shown is not None:
        delivery = "выберите город, чтобы увидеть доставку" if city is None else _delivery_line(info)
        if _known(info):
            total = f"{_money(shown.price + info.price)} ₽"
    return {
        "product": favorite.product,
        "image_url": image_of(favorite.product),
        "shop": shown.shop.name if shown is not None else "",
        "fixed": "—" if fixed is None else f"{_money(fixed)} ₽",
        "current": "нет в наличии" if current is None else f"{_money(current)} ₽",
        "trend": None if diff is None else ("down" if diff < 0 else "up" if diff > 0 else "same"),
        "diff": "" if not diff else f"{'−' if diff < 0 else '+'}{_money(abs(diff))} ₽",
        "delivery": delivery,
        "total": total,
    }


def favorite_list(request):
    favorites = list(owners.favorites_with_prices(request))
    city = current_city(request)
    shown = {f.id: _shown_offer(f) for f in favorites}
    infos = ranking.delivery_map([o for o in shown.values() if o is not None], city)
    rows = [_row(f, shown[f.id], infos, city) for f in favorites]
    return render(request, "favorites/list.html", {"rows": rows})


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "favorites/notifications.html", {"notifications": items})
