import hmac
import hashlib
from django.contrib.auth import login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


def check_telegram_auth(init_data: dict) -> bool:
    """
    Проверяет подпись initData от Telegram
    """
    hash_received = init_data.pop("hash", None)
    data_check_arr = [f"{k}={v}" for k, v in sorted(init_data.items())]
    data_check_string = "\n".join(data_check_arr)

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=settings.TELEGRAM_BOT_TOKEN.encode(),
        digestmod=hashlib.sha256
    ).digest()

    hash_calculated = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(hash_received, hash_calculated)


def telegram_admin_login(request):
    # initData может приходить как GET-параметры
    init_data = request.GET.dict()
    print('GET', init_data)
    if not check_telegram_auth(init_data):
        return HttpResponseForbidden("Invalid Telegram auth")

    telegram_id = init_data.get("user[id]")
    if not telegram_id:
        return HttpResponseForbidden("Telegram ID not found")

    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return HttpResponseForbidden("User not allowed")

    # Логиним
    login(request, user)

    return redirect("/admin/")
