from urllib.parse import urlparse

from django.contrib import messages
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalog.models import Offer
from delivery.models import City

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


def results(request, search_id):
    """Дашборд. GET: sort (price|delivery|rating|total), price_max, delivery_max_days, shop, in_stock."""
    search = _own_search(request, search_id)
    return render(request, "results.html", {
        "search": search,
        "recommendation": None,  # {offer, explanation, facts}
        "items": [],             # магазин, товар, цена, доставка, итого, рейтинг, is_recommended, is_favorite
        "warnings": ["Результаты пока не рассчитываются"] if search.status == "done" else [],
    })


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
