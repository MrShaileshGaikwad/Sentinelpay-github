from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("new/", views.payment_create, name="new"),
    path("", views.payment_list, name="list"),
    path("<uuid:public_ref>/", views.payment_detail, name="detail"),
]
