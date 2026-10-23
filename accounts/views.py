from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from favorites.models import Favorite
from search.models import SearchRequest

from .forms import RegisterForm


def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Регистрация прошла успешно")
        return redirect("search:home")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def cabinet(request):
    """Личный кабинет: история запросов и избранное."""
    return render(request, "accounts/cabinet.html", {
        "history": SearchRequest.objects.filter(user=request.user).order_by("-created_at")[:20],
        "favorites": Favorite.objects.filter(user=request.user).select_related("product"),
    })
