from dataclasses import dataclass
from decimal import Decimal

PAYMENT_METHODS = [
    ("card_online", "Картой онлайн"),
    ("card_on_receipt", "Картой при получении"),
    ("cash", "Наличными"),
    ("sbp", "СБП"),
    ("installment", "Рассрочка или кредит"),
]
PAYMENT_LABELS = dict(PAYMENT_METHODS)


@dataclass(frozen=True)
class OfferTerms:
    rating: Decimal | None
    rating_count: int
    payment_methods: tuple
    return_days: int | None
    warranty_months: int | None

    @property
    def payment_labels(self):
        return [PAYMENT_LABELS[code] for code in self.payment_methods if code in PAYMENT_LABELS]
