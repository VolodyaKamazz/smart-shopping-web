from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import Offer, Product

from . import owners
from .models import Notification


def _money(value):
    return f"{value:,.0f}".replace(",", "\u00a0")


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


def _offer_from(request):
    raw = request.POST.get("offer_id", "")
    return Offer.objects.filter(pk=int(raw)).first() if raw.isdigit() else None


@require_POST
def toggle(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    favorite = owners.toggle_favorite(request, product, _offer_from(request))
    if _wants_json(request):
        return JsonResponse({
            "is_favorite": favorite is not None,
            "product_id": product.id,
            "price_at_add": None if favorite is None or favorite.price_at_add is None else float(favorite.price_at_add),
        })
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("favorites:list")


def _row(favorite):
    current = owners.current_price(favorite)
    fixed = favorite.price_at_add
    diff = None if current is None or fixed is None else current - fixed
    offer = favorite.offer
    return {
        "product": favorite.product,
        "shop": offer.shop.name if offer is not None else "",
        "fixed": "—" if fixed is None else f"{_money(fixed)} ₽",
        "current": "нет в наличии" if current is None else f"{_money(current)} ₽",
        "trend": None if diff is None else ("down" if diff < 0 else "up" if diff > 0 else "same"),
        "diff": "" if not diff else f"{'−' if diff < 0 else '+'}{_money(abs(diff))} ₽",
    }


def favorite_list(request):
    rows = [_row(f) for f in owners.favorites_with_prices(request)]
    return render(request, "favorites/list.html", {"rows": rows})


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "favorites/notifications.html", {"notifications": items})
