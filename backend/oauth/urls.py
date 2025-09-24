from django.urls import path
from .views import telegram_admin_login

urlpatterns = [
    path("twa/", telegram_admin_login, name="twa-admin-login"),
]
