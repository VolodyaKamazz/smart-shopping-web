from django.core.exceptions import ValidationError

from .terms import PAYMENT_METHODS

PAYMENT_CODES = {code for code, _ in PAYMENT_METHODS}


def validate_payment_methods(value):
    if not isinstance(value, list):
        raise ValidationError("Нужен список способов оплаты")
    unknown = sorted({str(code) for code in value} - PAYMENT_CODES)
    if unknown:
        raise ValidationError("Неизвестные способы оплаты: %(codes)s", params={"codes": ", ".join(unknown)})
    if len(set(value)) != len(value):
        raise ValidationError("Способы оплаты повторяются")
