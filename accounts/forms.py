from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("city", "delivery_priority", "budget_max")
        widgets = {
            "city": forms.Select(attrs={"class": "form-select"}),
            "delivery_priority": forms.Select(attrs={"class": "form-select"}),
            "budget_max": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "100", "placeholder": "Например: 50000"}),
        }
        labels = {
            "city": "Город доставки",
            "delivery_priority": "Что важнее",
            "budget_max": "Максимальный бюджет, ₽",
        }

    def clean_budget_max(self):
        value = self.cleaned_data.get("budget_max")
        if value is not None and value <= 0:
            raise forms.ValidationError("Бюджет должен быть больше нуля")
        return value
