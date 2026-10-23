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
