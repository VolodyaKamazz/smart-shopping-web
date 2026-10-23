"""Чистые функции без обращений к БД: данные приходят параметрами."""


def rank(offers: list, profile: dict) -> list:
    """Скоринг: жёсткие условия, нормировка, веса по приоритету (баланс/цена/скорость). TODO."""
    raise NotImplementedError


def build_explanation(best, others: list) -> tuple:
    """Факты (цена, доставка, срок, экономия) -> текст по шаблону. Возвращает (text, facts). TODO."""
    raise NotImplementedError
