from django.test import TestCase
from django.urls import reverse

from .models import User


class AccountsTests(TestCase):
    def test_register_and_cabinet(self):
        r = self.client.post(reverse("accounts:register"), {
            "username": "u1", "email": "u1@example.com", "password1": "Str0ng-pass-123", "password2": "Str0ng-pass-123"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(email="u1@example.com").exists())
        self.assertEqual(self.client.get(reverse("accounts:cabinet")).status_code, 200)

    def test_cabinet_requires_login(self):
        self.assertEqual(self.client.get(reverse("accounts:cabinet")).status_code, 302)


class ProfileTests(TestCase):
    def setUp(self):
        from delivery.models import City
        self.city = City.objects.create(name="Екатеринбург")
        self.user = User.objects.create_user("u2", "u2@example.com", "Str0ng-pass-123")

    def test_profile_requires_login(self):
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 302)

    def test_profile_saves_city_priority_budget(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("accounts:profile"), {
            "city": self.city.pk, "delivery_priority": "speed", "budget_max": "45000"})
        self.assertRedirects(r, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.city, self.city)
        self.assertEqual(self.user.delivery_priority, "speed")
        self.assertEqual(int(self.user.budget_max), 45000)

    def test_profile_rejects_negative_budget(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("accounts:profile"), {"delivery_priority": "price", "budget_max": "-5"})
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.budget_max)
