from django.shortcuts import render
from django.contrib.auth import login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


def telegram_admin_login(request):
    telegram_id = request.GET.get('telegram_id')
    if not telegram_id:
        return redirect('/admin/login/')

    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return redirect('/admin/login/?redirected=true')

    # Логиним
    login(request, user)

    return redirect("/admin/")
