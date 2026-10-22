from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from banking import views as banking_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", banking_views.dashboard, name="dashboard"),
    path("profile/", banking_views.customer_profile, name="customer-profile"),
    path("payments/", include("payments.urls")),
]
