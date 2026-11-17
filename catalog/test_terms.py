from decimal import Decimal

from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.test import TestCase

from catalog.admin import ShopAdminForm
from catalog.models import Shop
from catalog.terms import OfferTerms
from catalog.validators import validate_payment_methods
from delivery.testing import make_offer


class PaymentMethodsValidatorTests(TestCase):
    def test_known_codes_pass(self):
        validate_payment_methods(["card_online", "cash"])
        validate_payment_methods([])

    def test_unknown_code_is_rejected_and_named(self):
        with self.assertRaisesMessage(ValidationError, "bitcoin"):
            validate_payment_methods(["cash", "bitcoin"])


class ShopRatingValidationTests(TestCase):
    def full_clean(self, rating):
        shop = Shop(name="Магазин", rating=rating)
        shop.full_clean()

    def test_rating_out_of_range(self):
        for rating in ("-0.1", "5.01", "9.99"):
            with self.assertRaises(ValidationError, msg=rating):
                self.full_clean(Decimal(rating))


class OfferTermsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = Shop.objects.create(name="Магазин", rating=Decimal("4.50"), rating_count=120, return_days=14,
                                       warranty_months=12, payment_methods=["cash", "sbp"])

    def test_offer_warranty_overrides_shop(self):
        self.assertEqual(make_offer(self.shop, warranty_months=24).effective_warranty_months, 24)

    def test_zero_offer_warranty_is_not_replaced_by_shop_value(self):
        self.assertEqual(make_offer(self.shop, warranty_months=0).effective_warranty_months, 0)

    def test_shop_warranty_is_used_when_offer_has_none(self):
        self.assertEqual(make_offer(self.shop).effective_warranty_months, 12)

    def test_terms_collect_shop_and_offer_conditions(self):
        self.assertEqual(make_offer(self.shop, warranty_months=24).terms,
                         OfferTerms(Decimal("4.50"), 120, ("cash", "sbp"), 14, 24))


class PaymentLabelsTests(TestCase):
    def test_labels_follow_codes_and_skip_unknown(self):
        terms = OfferTerms(None, 0, ("sbp", "legacy", "cash"), None, None)
        self.assertEqual(terms.payment_labels, ["СБП", "Наличными"])


class ShopAdminFieldsetTests(TestCase):
    def test_fieldsets_cover_every_editable_shop_field(self):
        shop_admin = site._registry[Shop]
        listed = [name for _, options in shop_admin.fieldsets for name in options["fields"]]
        editable = [f.name for f in Shop._meta.get_fields() if getattr(f, "editable", False) and not f.auto_created]
        self.assertCountEqual(listed, editable)


class ShopAdminFormTests(TestCase):
    def data(self, **overrides):
        data = {"name": "Новый", "url": "", "rating": "4.2", "rating_count": 10, "return_days": 7,
                "warranty_months": 12, "payment_methods": ["card_online", "sbp"], "refresh_hours": 6,
                "category_map": "{}", "is_active": "on"}
        data.update(overrides)
        return data

    def test_payment_methods_are_saved_as_list_of_codes(self):
        form = ShopAdminForm(self.data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().payment_methods, ["card_online", "sbp"])

    def test_rating_above_five_is_rejected(self):
        self.assertIn("rating", ShopAdminForm(self.data(rating="6")).errors)
