from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DeliveryInfo:
    price: Decimal
    min_days: int
    max_days: int
    source: str  # shop | cdek | zone


def calc_delivery(offer, city) -> DeliveryInfo:
    """Порядок: ShopDeliveryRule -> API СДЭК (кэш 24 ч) -> ZoneRate. TODO."""
    raise NotImplementedError
