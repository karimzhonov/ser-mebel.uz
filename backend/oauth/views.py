from django.shortcuts import render
from django.contrib.auth import login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


def telegram_admin_login(request):
    telegram_id = request.POST.get('telegram_id')
    if not telegram_id:
        return HttpResponseForbidden("Telegram ID not found")

    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return HttpResponseForbidden("User not allowed")

    # Логиним
    login(request, user)

    return redirect("/admin/")
