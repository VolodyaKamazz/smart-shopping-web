import time

from django.utils import timezone

from .models import SearchRequest


def run_search(search_id):
    """Конвейер поиска: разбор запроса -> товары и предложения -> доставка -> скоринг -> объяснение.
    Пока заглушка: сразу помечает запрос выполненным, чтобы работал сквозной путь экранов."""
    started = time.monotonic()
    search = SearchRequest.objects.get(pk=search_id)
    search.status = "running"
    search.step = "Разбор запроса"
    search.save(update_fields=["status", "step"])
    # TODO: services из catalog, delivery, recommender
    search.status = "done"
    search.step = ""
    search.finished_at = timezone.now()
    search.duration_ms = int((time.monotonic() - started) * 1000)
    search.save(update_fields=["status", "step", "finished_at", "duration_ms"])
