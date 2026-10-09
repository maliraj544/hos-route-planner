from django.urls import path
from .views import health, plan_trip

urlpatterns = [
    path("health/", health),
    path("plan/", plan_trip),
]
