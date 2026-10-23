from django.urls import path

from . import views

app_name = "favorites"
urlpatterns = [
    path("favorites/<int:product_id>/toggle/", views.toggle, name="toggle"),
    path("notifications/", views.notifications, name="notifications"),
]
