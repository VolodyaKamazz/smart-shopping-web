from dataclasses import dataclass
from decimal import Decimal

from .models import DeliveryMethod

SOURCE_SHOP = "shop"
SOURCE_ZONE = "zone"
SOURCE_UNKNOWN = "unknown"


def format_days(min_days, max_days):
    return f"{min_days}" if min_days == max_days else f"{min_days}–{max_days}"


@dataclass
class DeliveryInfo:
    price: Decimal | None
    min_days: int | None
    max_days: int | None
    source: str
    method: str = DeliveryMethod.COURIER.value

    @property
    def is_known(self):
        return self.price is not None
