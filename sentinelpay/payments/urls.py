from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("new/", views.payment_create, name="new"),
    path("review/", views.payment_review, name="review"),
    path("statement.csv", views.statement_csv, name="statement-csv"),
    path("fraud/", views.fraud_center, name="fraud-center"),
    path("fraud/cases/<int:case_id>/", views.fraud_case_detail, name="fraud-case"),
    path("", views.payment_list, name="list"),
    path("<uuid:public_ref>/", views.payment_detail, name="detail"),
]
