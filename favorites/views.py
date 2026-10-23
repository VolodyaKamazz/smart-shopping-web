from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product

from .models import Favorite, Notification


@login_required
@require_POST
def toggle(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    fav, created = Favorite.objects.get_or_create(user=request.user, product=product)
    if not created:
        fav.delete()
    return redirect(request.POST.get("next") if (request.POST.get("next") or "").startswith("/") else "accounts:cabinet")


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "favorites/notifications.html", {"notifications": items})
