from catalog.models import DATA_STALE_AFTER

STALE_HOURS = int(DATA_STALE_AFTER.total_seconds() // 3600)

DELIVERY_FAILED = "delivery_failed"
DEADLINE_HIT = "deadline"
EXPLANATION_FAILED = "explanation_failed"

MESSAGES = {
    DELIVERY_FAILED: "Не удалось рассчитать доставку для части предложений, итоговая цена может быть неполной",
    DEADLINE_HIT: "Поиск занял больше времени, чем рассчитано: доставка посчитана не для всех предложений",
    EXPLANATION_FAILED: "Не удалось подготовить объяснение рекомендации",
}


def stale_message(names):
    subject = f"магазина «{names[0]}»" if len(names) == 1 else "магазинов " + ", ".join(f"«{name}»" for name in names)
    return f"Данные {subject} не обновлялись больше {STALE_HOURS} часов, цены и наличие могут отличаться"


def warning_messages(facts):
    messages = [MESSAGES[reason] for reason in facts.get("degraded_reasons", []) if reason in MESSAGES]
    if facts.get("stale_shops"):
        messages.append(stale_message(facts["stale_shops"]))
    return messages
