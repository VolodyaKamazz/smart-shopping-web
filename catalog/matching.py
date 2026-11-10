import logging
from collections import Counter, defaultdict

from django.db import connection

from .models import Brand, Category, Product
from .normalize import build_match_key, build_search_text, normalize_brand, valid_gtins

logger = logging.getLogger(__name__)

MAX_MODEL_LEN = 200
MAX_MPN_LEN = 100
MAX_BRAND_LEN = 200


class _ProductIndex:
    def __init__(self, gtins: set, keys: set):
        self._by_gtin = {}
        self._by_key = defaultdict(list)
        for product in self._load("gtin", gtins):
            self._by_gtin.setdefault(product.gtin, product)
        for product in self._load("match_key", keys):
            self._by_key[product.match_key].append(product)

    @staticmethod
    def _load(field: str, values: set):
        if not values:
            return []
        return (Product.objects.filter(**{f"{field}__in": values})
                .only("id", "category_id", "gtin", "match_key").order_by("pk"))

    def find(self, gtins: tuple, key: str, category_id: int) -> tuple:
        product = next((self._by_gtin[gtin] for gtin in gtins if gtin in self._by_gtin), None)
        if product:
            return product, "gtin"
        product = next((candidate for candidate in self._by_key.get(key, ())
                        if candidate.category_id == category_id and not (candidate.gtin and gtins)), None)
        return (product, "key") if product else (None, None)

    def add(self, product: Product) -> None:
        if product.gtin:
            self._by_gtin.setdefault(product.gtin, product)
        if product.match_key:
            self._by_key[product.match_key].append(product)

    def set_gtin(self, product: Product, gtin: str) -> None:
        product.gtin = gtin
        self._by_gtin.setdefault(gtin, product)


def _brands(items: list) -> dict:
    names = {}
    for item in items:
        normalized = normalize_brand(item.vendor)
        if 0 < len(normalized) <= MAX_BRAND_LEN:
            names.setdefault(normalized, item.vendor[:MAX_BRAND_LEN])
    found = {brand.normalized_name: brand for brand in Brand.objects.filter(normalized_name__in=names)}
    missing = [Brand(name=name, normalized_name=normalized) for normalized, name in names.items()
               if normalized not in found]
    if missing:
        Brand.objects.bulk_create(missing, ignore_conflicts=True)
        found.update((brand.normalized_name, brand)
                     for brand in Brand.objects.filter(normalized_name__in=[b.normalized_name for b in missing]))
    return found


def _new_product(item, category: Category, brand, gtins: tuple, key: str) -> Product:
    return Product(
        category=category, brand=brand, name=item.title, model=item.model[:MAX_MODEL_LEN],
        gtin=gtins[0] if gtins else "", mpn=item.vendor_code[:MAX_MPN_LEN], match_key=key,
        search_text=build_search_text(item.title, item.vendor, item.model, item.vendor_code),
        attributes=item.params)


def _save_new(products: list) -> None:
    if connection.features.can_return_rows_from_bulk_insert:
        Product.objects.bulk_create(products)
    else:
        for product in products:
            product.save()


def _warn_missing_categories(slugs: Counter) -> None:
    for slug, count in slugs.items():
        logger.warning("Категория %r из Shop.category_map не найдена в каталоге: %d предложений без товара",
                       slug, count)


def match_offers(items) -> list:
    items = list(items)
    if not items:
        return []
    all_gtins = [valid_gtins(item.barcodes) for item in items]
    keys = [build_match_key(item.vendor, item.model) for item in items]
    categories = {c.slug: c for c in Category.objects.filter(slug__in={item.category_slug for item in items})}
    brands = _brands(items)
    index = _ProductIndex({gtin for gtins in all_gtins for gtin in gtins}, set(keys) - {""})

    products, created, enriched = [], [], []
    by = Counter()
    missing_categories = Counter()
    for item, gtins, key in zip(items, all_gtins, keys):
        category = categories.get(item.category_slug)
        if category is None:
            missing_categories[item.category_slug] += 1
            by["no_category"] += 1
            products.append(None)
            continue
        product, via = index.find(gtins, key, category.pk)
        if product is None:
            product, via = _new_product(item, category, brands.get(normalize_brand(item.vendor)), gtins, key), "new"
            index.add(product)
            created.append(product)
        elif via == "key" and gtins and not product.gtin:
            index.set_gtin(product, gtins[0])
            if product.pk:
                enriched.append(product)
        by[via] += 1
        products.append(product)

    if enriched:
        Product.objects.bulk_update(enriched, ["gtin"])
    if created:
        _save_new(created)
    _warn_missing_categories(missing_categories)
    logger.debug("Сопоставление: %d предложений, по gtin %d, по match_key %d, новых товаров %d, без категории %d",
                len(items), by["gtin"], by["key"], by["new"], by["no_category"])
    return [product.pk if product else None for product in products]