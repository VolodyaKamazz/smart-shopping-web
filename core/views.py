from django.shortcuts import render


def home(request):
    """Главная страница: поиск. Пока отдаёт заглушку-шаблон."""
    return render(request, "index.html")


def results(request):
    """Дашборд: таблица сравнения предложений. Пока отдаёт заглушку-шаблон."""
    return render(request, "results.html")
