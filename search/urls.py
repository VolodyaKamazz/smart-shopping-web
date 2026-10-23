from django.urls import path

from . import views

app_name = "search"
urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.start_search, name="start"),
    path("search/<uuid:search_id>/wait/", views.wait, name="wait"),
    path("search/<uuid:search_id>/status/", views.status, name="status"),
    path("results/<uuid:search_id>/", views.results, name="results"),
    path("results/<uuid:search_id>/feedback/", views.feedback, name="feedback"),
    path("go/<int:offer_id>/", views.go, name="go"),
]
