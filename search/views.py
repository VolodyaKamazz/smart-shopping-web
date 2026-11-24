from urllib.parse import urlparse

from django.contrib import messages
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import Offer
from favorites.owners import favorite_product_ids

from . import ranking
from .city import city_from, current_city, remember_city
from .images import image_of
from .listing import current_sort, select_results, shops_of
from .models import OfferClick, SearchRequest


def home(request):
    return render(request, "index.html")


@require_POST
def start_search(request):
    query = request.POST.get("query", "").strip()[:300]
    if not query:
        messages.error(request, "Введите, что вы хотите купить")
        return redirect("search:home")
    if not request.session.session_key:
        request.session.create()
    user = request.user if request.user.is_authenticated else None
    city = city_from(request.POST.get("city")) or current_city(request)
    search = SearchRequest.objects.create(user=user, session_key=request.session.session_key, raw_query=query, city=city)
    from django_q.tasks import async_task  # в режиме sync выполняется сразу
    async_task("search.tasks.run_search", str(search.id))
    return redirect("search:wait", search_id=search.id)


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


def _safe_next(request):
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse("search:home")


@require_POST
def set_city(request):
    raw = (request.POST.get("city") or "").strip()
    city = city_from(raw)
    if raw and city is None:
        if _wants_json(request):
            return JsonResponse({"error": "unknown_city"}, status=400)
        messages.error(request, "Такого города нет в списке")
        return redirect(_safe_next(request))
    remember_city(request, city)
    if _wants_json(request):
        return JsonResponse({"city": None if city is None else {"id": city.id, "name": city.name}})
    return redirect(_safe_next(request))


def _own_search(request, search_id):
    search = get_object_or_404(SearchRequest, pk=search_id)
    owner_ok = (search.user_id and search.user_id == request.user.id) or (
        not search.user_id and search.session_key == request.session.session_key)
    if not owner_ok:
        raise Http404
    return search


def wait(request, search_id):
    return render(request, "search/wait.html", {"search": _own_search(request, search_id)})


def status(request, search_id):
    search = _own_search(request, search_id)
    return JsonResponse({"status": search.status, "step": search.step,
                         "redirect_url": reverse("search:results", args=[search.id]) if search.status == "done" else None})


def _money(value):
    return f"{value:,.0f}".replace(",", "\u00a0")


def _delivery_text(result):
    if result.delivery_price is None:
        return "—"
    price = "бесплатно" if result.delivery_price == 0 else f"{_money(result.delivery_price)} ₽"
    low, high = result.delivery_min_days, result.delivery_max_days
    if low is None or high is None:
        return price
    days = f"{low} дн." if low == high else f"{low}–{high} дн."
    return f"{price}, {days}"


def _result_item(result, favorites=frozenset()):
    offer = result.offer
    return {
        "offer_id": offer.id,
        "shop": offer.shop.name,
        "title": offer.title_raw,
        "price": _money(result.item_price),
        "delivery": _delivery_text(result),
        "total": _money(result.total_price),
        "rating": offer.shop.rating,
        "is_recommended": result.is_recommended,
        "is_favorite": offer.product_id in favorites,
        "image_url": image_of(offer.product),
    }


def _current_criterion(search):
    value = search.facts.get("criterion") if isinstance(search.facts, dict) else None
    return value if value in ranking.PRIORITIES else "balanced"


def _sync_city(request, search):
    city = current_city(request)
    if city is not None and search.status == "done" and search.city_id != city.id:
        ranking.change_city(search, city)


def _sync_criterion(request, search):
    chosen = request.GET.get("criterion")
    if search.status == "done" and chosen in ranking.PRIORITIES and chosen != search.facts.get("criterion"):
        ranking.recalculate(search, chosen)


def _recommendation(search):
    offer = search.recommended_offer
    if offer is None:
        return None
    return {"offer_id": offer.id, "shop": offer.shop.name, "title": offer.title_raw,
            "explanation": search.explanation, "facts": search.facts}


def _warnings(search, items):
    facts = search.facts if isinstance(search.facts, dict) else {}
    if search.status == "done" and not items and not search.results.exists() and facts.get("excluded_over_budget"):
        return [f"Все найденные предложения дороже вашего бюджета ({_money(facts['budget_max'])} ₽)"]
    return []


def _float(value):
    return None if value is None else float(value)


def _api_item(result, favorites=frozenset()):
    offer = result.offer
    terms = offer.terms
    return {
        "offer_id": offer.id,
        "product_id": offer.product_id,
        "is_favorite": offer.product_id in favorites,
        "shop_id": offer.shop_id,
        "image_url": image_of(offer.product),
        "shop": offer.shop.name,
        "title": offer.title_raw,
        "price": _float(result.item_price),
        "delivery_price": _float(result.delivery_price),
        "delivery_min_days": result.delivery_min_days,
        "delivery_max_days": result.delivery_max_days,
        "total_price": _float(result.total_price),
        "rating": _float(offer.shop.rating),
        "rank": result.rank,
        "score": result.score,
        "is_recommended": result.is_recommended,
        "payment_methods": terms.payment_labels,
        "return_days": terms.return_days,
        "warranty_months": terms.warranty_months,
        "url": reverse("search:go", args=[offer.id]),
    }


def results(request, search_id):
    """Дашборд. GET: criterion (balanced|price|speed), sort (price|delivery|rating|total), price_min, price_max, shop, delivery_max_days."""
    search = _own_search(request, search_id)
    _sync_city(request, search)
    _sync_criterion(request, search)
    favorites = favorite_product_ids(request)
    items = [_result_item(r, favorites) for r in select_results(search, request.GET)]
    return render(request, "results.html", {
        "search": search,
        "recommendation": _recommendation(search),
        "items": items,
        "criterion": _current_criterion(search),
        "criteria": ranking.CRITERIA,
        "sort": current_sort(request.GET),
        "warnings": _warnings(search, items),
    })


def results_api(request, search_id):
    search = _own_search(request, search_id)
    _sync_city(request, search)
    _sync_criterion(request, search)
    selected = select_results(search, request.GET)
    favorites = favorite_product_ids(request)
    return JsonResponse({
        "status": search.status,
        "criterion": _current_criterion(search),
        "sort": current_sort(request.GET) or "recommendation",
        "recommendation": _recommendation(search),
        "count": len(selected),
        "city": None if search.city is None else {"id": search.city.id, "name": search.city.name},
        "shops": shops_of(search),
        "items": [_api_item(r, favorites) for r in selected],
    }, json_dumps_params={"ensure_ascii": False})


@require_POST
def feedback(request, search_id):
    search = _own_search(request, search_id)
    search.helpful = request.POST.get("helpful") == "1"
    search.feedback_comment = request.POST.get("comment", "")[:1000]
    search.save(update_fields=["helpful", "feedback_comment"])
    messages.success(request, "Спасибо за оценку")
    return redirect("search:results", search_id=search.id)


def go(request, offer_id):
    offer = get_object_or_404(Offer, pk=offer_id)
    if urlparse(offer.url).scheme not in ("http", "https"):
        raise Http404
    OfferClick.objects.create(offer=offer, user=request.user if request.user.is_authenticated else None,
                              session_key=request.session.session_key or "")
    return redirect(offer.url)
