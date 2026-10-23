from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    keywords = models.TextField(blank=True, help_text="Синонимы через запятую для разбора запроса")

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=500)
    model = models.CharField(max_length=200, blank=True)
    gtin = models.CharField(max_length=20, blank=True, db_index=True)
    mpn = models.CharField(max_length=100, blank=True)
    match_key = models.CharField(max_length=300, blank=True, db_index=True)
    search_text = models.TextField(blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(max_length=500, blank=True)

    def __str__(self):
        return self.name


class Shop(models.Model):
    name = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    rating_count = models.PositiveIntegerField(default=0)
    origin_city = models.ForeignKey("delivery.City", null=True, blank=True, on_delete=models.SET_NULL)
    return_days = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_methods = models.JSONField(default=list, blank=True)
    warranty_months = models.PositiveSmallIntegerField(null=True, blank=True)
    feed_url = models.URLField(max_length=500, blank=True)
    refresh_hours = models.PositiveSmallIntegerField(default=6)
    category_map = models.JSONField(default=dict, blank=True, help_text="categoryId фида -> slug категории")
    last_import_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Offer(models.Model):
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="offers")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="offers")
    external_id = models.CharField(max_length=100)
    url = models.URLField(max_length=1000)
    title_raw = models.CharField(max_length=500)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    old_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    in_stock = models.BooleanField(default=True)
    warranty_months = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_g = models.PositiveIntegerField(null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["shop", "external_id"], name="uniq_offer_shop_external")]
        indexes = [models.Index(fields=["product", "is_active", "in_stock", "price"])]

    def __str__(self):
        return self.title_raw


class PriceHistory(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="history")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    in_stock = models.BooleanField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["offer", "recorded_at"])]
