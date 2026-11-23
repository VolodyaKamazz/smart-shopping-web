from urllib.parse import urlparse

from django.contrib import messages
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalog.models import Offer
from delivery.models import City

from . import degraded, ranking
from .listing import current_sort, select_results
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
    city = City.objects.filter(pk=request.POST.get("city") or None).first() or (user.city if user else None)
    search = SearchRequest.objects.create(user=user, session_key=request.session.session_key, raw_query=query, city=city)
    from django_q.tasks import async_task  # в режиме sync выполняется сразу
    async_task("search.tasks.run_search", str(search.id))
    return redirect("search:wait", search_id=search.id)


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


def _result_item(result):
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
        "is_favorite": False,
    }


def _current_criterion(search):
    value = search.facts.get("criterion") if isinstance(search.facts, dict) else None
    return value if value in ranking.PRIORITIES else "balanced"


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
    warnings = []
    if search.status == "done" and not items and not search.results.exists() and facts.get("excluded_over_budget"):
        warnings.append(f"Все найденные предложения дороже вашего бюджета ({_money(facts['budget_max'])} ₽)")
    return warnings + degraded.warning_messages(facts)


def _float(value):
    return None if value is None else float(value)


def _api_item(result):
    offer = result.offer
    terms = offer.terms
    return {
        "offer_id": offer.id,
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
    """Дашборд. GET: criterion (balanced|price|speed), sort (price|delivery|rating|total), price_max, delivery_max_days."""
    search = _own_search(request, search_id)
    _sync_criterion(request, search)
    items = [_result_item(r) for r in select_results(search, request.GET)]
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
    _sync_criterion(request, search)
    selected = select_results(search, request.GET)
    return JsonResponse({
        "status": search.status,
        "criterion": _current_criterion(search),
        "sort": current_sort(request.GET) or "recommendation",
        "recommendation": _recommendation(search),
        "count": len(selected),
        "items": [_api_item(r) for r in selected],
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
